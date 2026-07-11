from unittest.mock import MagicMock, patch

import pytest

from allspark import __version__
from allspark.__main__ import _build_parser, _resolve_args


def test_help_lists_standard_options(capsys):
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--version" in out
    assert "--web" in out
    assert "--host" in out
    assert "--port" in out


def test_version_uses_package_version(capsys):
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_web_defaults_to_localhost():
    args = _resolve_args(["--web"])
    assert args.web is True
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.db_path is None


def test_web_alias_accepts_host_port_and_db_path():
    args = _resolve_args(["web", "--host", "0.0.0.0", "--port", "9000", "custom.db"])
    assert args.web is True
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.db_path == "custom.db"


@patch("allspark.__main__.uvicorn.run")
@patch("allspark.__main__.create_app")
def test_main_warns_when_binding_all_interfaces(create_app, uvicorn_run, caplog):
    import allspark.__main__ as main_mod

    create_app.return_value = MagicMock()
    with patch.object(main_mod, "_port_in_use", return_value=False):
        main_mod.main(["--web", "--host", "0.0.0.0"])

    assert "0.0.0.0" in caplog.text
    uvicorn_run.assert_called_once()
