import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Callable

from allspark.models import KnowledgeEntry


class ChannelType(Enum):
    WIFI_DIRECT = "wifi_direct"
    BLUETOOTH = "bluetooth"
    LAN = "lan"
    NFC = "nfc"
    LORA = "lora"
    PHYSICAL = "physical"


class NodeStatus(Enum):
    DISCOVERED = "discovered"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    EXCHANGING = "exchanging"
    DISCONNECTED = "disconnected"


@dataclass
class SparkNode:
    node_id: str
    spark_id: str
    address: str
    port: int
    channel: ChannelType
    status: NodeStatus = NodeStatus.DISCOVERED
    knowledge_count: int = 0
    categories: list = field(default_factory=list)
    last_seen: str = ""
    display_name: str = ""

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "spark_id": self.spark_id,
            "address": self.address,
            "port": self.port,
            "channel": self.channel.value,
            "status": self.status.value,
            "knowledge_count": self.knowledge_count,
            "categories": self.categories,
            "last_seen": self.last_seen,
            "display_name": self.display_name,
        }


@dataclass
class NetworkMessage:
    msg_type: str
    sender_id: str
    payload: dict
    timestamp: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "msg_type": self.msg_type,
            "sender_id": self.sender_id,
            "payload": self.payload,
            "timestamp": self.timestamp or datetime.now().isoformat(),
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "NetworkMessage":
        d = json.loads(data)
        return cls(
            msg_type=d.get("msg_type", ""),
            sender_id=d.get("sender_id", ""),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", ""),
        )


DISCOVERY_PORT = 7979
EXCHANGE_PORT = 7980
BEACON_INTERVAL = 30
DISCOVERY_TIMEOUT = 10


class SparkNetwork:
    def __init__(self, db=None, spark_id: str = "", llm_engine=None):
        self.db = db
        self.spark_id = spark_id or f"spark-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}"
        self.llm = llm_engine
        self.nodes: dict[str, SparkNode] = {}
        self.channel_status: dict[ChannelType, bool] = {
            ChannelType.WIFI_DIRECT: False,
            ChannelType.BLUETOOTH: False,
            ChannelType.LAN: False,
            ChannelType.NFC: False,
            ChannelType.LORA: False,
            ChannelType.PHYSICAL: True,
        }
        self._running = False
        self._discovery_thread: Optional[threading.Thread] = None
        self._beacon_thread: Optional[threading.Thread] = None
        self._on_node_discovered: Optional[Callable] = None
        self._on_knowledge_received: Optional[Callable] = None

    def detect_channels(self) -> dict[str, bool]:
        results = {}

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            self.channel_status[ChannelType.LAN] = True
            results["lan"] = {"available": True, "ip": local_ip}
        except Exception:
            self.channel_status[ChannelType.LAN] = False
            results["lan"] = {"available": False}

        try:
            import subprocess
            if self._is_macos():
                output = subprocess.check_output(
                    ["system_profiler", "SPBluetoothDataType"],
                    stderr=subprocess.DEVNULL, timeout=5
                ).decode("utf-8", errors="ignore")
                bt_available = "Bluetooth" in output and "Not Available" not in output
            else:
                output = subprocess.check_output(
                    ["bluetoothctl", "show"],
                    stderr=subprocess.DEVNULL, timeout=5
                ).decode("utf-8", errors="ignore")
                bt_available = "Powered: yes" in output

            self.channel_status[ChannelType.BLUETOOTH] = bt_available
            results["bluetooth"] = {"available": bt_available}
        except Exception:
            self.channel_status[ChannelType.BLUETOOTH] = False
            results["bluetooth"] = {"available": False}

        try:
            if self._is_macos():
                output = subprocess.check_output(
                    ["networksetup", "-listallhardwareports"],
                    stderr=subprocess.DEVNULL, timeout=5
                ).decode("utf-8", errors="ignore")
                wifi_available = "Wi-Fi" in output
            else:
                wifi_available = Path("/sys/class/net/wlan0").exists()

            self.channel_status[ChannelType.WIFI_DIRECT] = wifi_available
            results["wifi_direct"] = {"available": wifi_available}
        except Exception:
            self.channel_status[ChannelType.WIFI_DIRECT] = False
            results["wifi_direct"] = {"available": False}

        results["nfc"] = {"available": False}
        results["lora"] = {"available": False}
        results["physical"] = {"available": True}

        return results

    def start_discovery(self, on_node_discovered: Optional[Callable] = None,
                        on_knowledge_received: Optional[Callable] = None) -> dict:
        if self._running:
            return {"status": "already_running"}

        if not self.channel_status.get(ChannelType.LAN, False):
            self.detect_channels()

        if not self.channel_status.get(ChannelType.LAN, False):
            return {"status": "error", "message": "No LAN channel available"}

        self._on_node_discovered = on_node_discovered
        self._on_knowledge_received = on_knowledge_received
        self._running = True

        self._beacon_thread = threading.Thread(target=self._broadcast_beacon, daemon=True)
        self._beacon_thread.start()

        self._discovery_thread = threading.Thread(target=self._listen_for_beacons, daemon=True)
        self._discovery_thread.start()

        return {"status": "started", "spark_id": self.spark_id}

    def stop_discovery(self) -> dict:
        self._running = False
        return {"status": "stopped", "nodes_found": len(self.nodes)}

    def get_known_nodes(self) -> list[dict]:
        return [n.to_dict() for n in self.nodes.values()]

    def get_knowledge_index(self) -> dict:
        if not self.db:
            return {"categories": {}, "total": 0}

        categories = {}
        rows = self.db.conn.execute(
            "SELECT category, COUNT(*) as cnt FROM knowledge GROUP BY category"
        ).fetchall()
        for r in rows:
            categories[r["category"]] = r["cnt"]

        total = self.db.conn.execute("SELECT COUNT(*) as cnt FROM knowledge").fetchone()["cnt"]

        return {
            "spark_id": self.spark_id,
            "categories": categories,
            "total": total,
        }

    def request_exchange(self, node_id: str, categories: list = None) -> dict:
        node = self.nodes.get(node_id)
        if not node:
            return {"status": "error", "message": f"Node {node_id} not found"}

        if node.status != NodeStatus.CONNECTED:
            return {"status": "error", "message": f"Node {node_id} not connected"}

        try:
            msg = NetworkMessage(
                msg_type="exchange_request",
                sender_id=self.spark_id,
                payload={
                    "categories": categories or [],
                    "index": self.get_knowledge_index(),
                },
            )

            response = self._send_tcp_message(node, msg)
            if response and response.msg_type == "exchange_response":
                return {
                    "status": "ok",
                    "remote_index": response.payload.get("index", {}),
                    "complementary": response.payload.get("complementary", []),
                }
            return {"status": "error", "message": "No response from node"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def send_knowledge(self, node_id: str, entry_ids: list[str]) -> dict:
        node = self.nodes.get(node_id)
        if not node:
            return {"status": "error", "message": f"Node {node_id} not found"}

        if not self.db:
            return {"status": "error", "message": "No database available"}

        entries = []
        for eid in entry_ids:
            entry = self.db.get_knowledge(eid)
            if entry:
                entries.append(entry)

        if not entries:
            return {"status": "error", "message": "No valid entries to send"}

        try:
            knowledge_data = []
            for k in entries:
                knowledge_data.append({
                    "id": k.id,
                    "category": k.category,
                    "subcategory": k.subcategory,
                    "priority": k.priority,
                    "title": k.title,
                    "summary": k.summary,
                    "steps": k.steps,
                    "prerequisites": k.prerequisites,
                    "warnings": k.warnings,
                    "verification": k.verification,
                    "source": k.source,
                    "version": k.version,
                    "language": k.language,
                })

            msg = NetworkMessage(
                msg_type="knowledge_transfer",
                sender_id=self.spark_id,
                payload={"entries": knowledge_data},
            )

            response = self._send_tcp_message(node, msg)
            if response and response.msg_type == "transfer_ack":
                return {
                    "status": "ok",
                    "sent_count": len(entries),
                    "accepted_count": response.payload.get("accepted_count", 0),
                }
            return {"status": "error", "message": "Transfer not acknowledged"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def receive_knowledge(self, entries_data: list[dict]) -> dict:
        if not self.db:
            return {"status": "error", "message": "No database available"}

        from allspark.knowledge_verifier import KnowledgeVerifier
        verifier = KnowledgeVerifier(self.db, self.llm)

        accepted = 0
        rejected = 0
        pending = 0

        for item in entries_data:
            entry = KnowledgeEntry(
                id=item.get("id", str(uuid.uuid4())[:8]),
                category=item.get("category", "uncategorized"),
                subcategory=item.get("subcategory", ""),
                priority=item.get("priority", 3),
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                steps=item.get("steps", []),
                prerequisites=item.get("prerequisites", []),
                warnings=item.get("warnings", []),
                verification=item.get("verification", "unverified"),
                source="other_spark",
                version=item.get("version", 1),
                language=item.get("language", "zh"),
            )

            report = verifier.verify_entry(entry)

            if report.level in ("expert_verified", "cross_ref", "field_tested"):
                entry.verification = report.level
                self.db.save_knowledge(entry)
                accepted += 1
            elif report.level == "conflict":
                rejected += 1
            else:
                entry.verification = "unverified"
                self.db.save_knowledge(entry)
                pending += 1

        if self._on_knowledge_received:
            self._on_knowledge_received(accepted, rejected, pending)

        return {
            "status": "ok",
            "accepted_count": accepted,
            "rejected_count": rejected,
            "pending_count": pending,
        }

    def get_status(self) -> dict:
        return {
            "spark_id": self.spark_id,
            "running": self._running,
            "channels": {ch.value: avail for ch, avail in self.channel_status.items()},
            "known_nodes": len(self.nodes),
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }

    def _broadcast_beacon(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        while self._running:
            try:
                beacon = NetworkMessage(
                    msg_type="spark_beacon",
                    sender_id=self.spark_id,
                    payload={
                        "knowledge_index": self.get_knowledge_index(),
                        "display_name": f"AllSpark-{self.spark_id[-4:]}",
                    },
                )
                data = beacon.to_json().encode("utf-8")
                sock.sendto(data, ("<broadcast>", DISCOVERY_PORT))
            except Exception:
                pass
            time.sleep(BEACON_INTERVAL)

        sock.close()

    def _listen_for_beacons(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.settimeout(DISCOVERY_TIMEOUT)

        while self._running:
            try:
                data, addr = sock.recvfrom(4096)
                msg = NetworkMessage.from_json(data.decode("utf-8"))

                if msg.msg_type == "spark_beacon" and msg.sender_id != self.spark_id:
                    self._handle_beacon(msg, addr[0])
            except socket.timeout:
                continue
            except Exception:
                pass

        sock.close()

    def _handle_beacon(self, msg: NetworkMessage, addr: str):
        payload = msg.payload
        index = payload.get("knowledge_index", {})
        node_id = msg.sender_id

        if node_id in self.nodes:
            self.nodes[node_id].last_seen = datetime.now().isoformat()
            self.nodes[node_id].knowledge_count = index.get("total", 0)
            self.nodes[node_id].categories = list(index.get("categories", {}).keys())
            self.nodes[node_id].status = NodeStatus.CONNECTED
        else:
            node = SparkNode(
                node_id=node_id,
                spark_id=node_id,
                address=addr,
                port=EXCHANGE_PORT,
                channel=ChannelType.LAN,
                status=NodeStatus.CONNECTED,
                knowledge_count=index.get("total", 0),
                categories=list(index.get("categories", {}).keys()),
                last_seen=datetime.now().isoformat(),
                display_name=payload.get("display_name", f"AllSpark-{node_id[-4:]}"),
            )
            self.nodes[node_id] = node

            if self._on_node_discovered:
                self._on_node_discovered(node)

    def _send_tcp_message(self, node: SparkNode, msg: NetworkMessage) -> Optional[NetworkMessage]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        try:
            sock.connect((node.address, node.port))
            sock.sendall(msg.to_json().encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)

            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            if response_data:
                return NetworkMessage.from_json(response_data.decode("utf-8"))
            return None
        except Exception:
            return None
        finally:
            sock.close()

    def start_exchange_server(self, host: str = "0.0.0.0", port: int = EXCHANGE_PORT) -> dict:
        def _handle_client(conn, addr):
            try:
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk

                if not data:
                    return

                msg = NetworkMessage.from_json(data.decode("utf-8"))

                if msg.msg_type == "exchange_request":
                    remote_index = msg.payload.get("index", {})
                    my_index = self.get_knowledge_index()
                    complementary = self._find_complementary(my_index, remote_index)

                    response = NetworkMessage(
                        msg_type="exchange_response",
                        sender_id=self.spark_id,
                        payload={"index": my_index, "complementary": complementary},
                    )
                    conn.sendall(response.to_json().encode("utf-8"))

                elif msg.msg_type == "knowledge_transfer":
                    entries = msg.payload.get("entries", [])
                    result = self.receive_knowledge(entries)

                    response = NetworkMessage(
                        msg_type="transfer_ack",
                        sender_id=self.spark_id,
                        payload={"accepted_count": result.get("accepted_count", 0)},
                    )
                    conn.sendall(response.to_json().encode("utf-8"))

            except Exception:
                pass
            finally:
                conn.close()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(5)
        server.settimeout(1)

        def _server_loop():
            while self._running:
                try:
                    conn, addr = server.accept()
                    t = threading.Thread(target=_handle_client, args=(conn, addr), daemon=True)
                    t.start()
                except socket.timeout:
                    continue
                except Exception:
                    break
            server.close()

        self._running = True
        t = threading.Thread(target=_server_loop, daemon=True)
        t.start()

        return {"status": "started", "host": host, "port": port}

    def _find_complementary(self, my_index: dict, remote_index: dict) -> list[str]:
        my_cats = set(my_index.get("categories", {}).keys())
        remote_cats = set(remote_index.get("categories", {}).keys())
        return list(remote_cats - my_cats)

    @staticmethod
    def _is_macos() -> bool:
        import platform
        return platform.system() == "Darwin"
