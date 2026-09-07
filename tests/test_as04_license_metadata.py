"""License evidence must use published metadata, never guess from package names."""
from email.message import Message
from types import SimpleNamespace

import pytest

from scripts.release_metadata import _copy_license_files, _license_name


@pytest.mark.parametrize("expression,license_value,classifiers,expected", [
    ("MIT", "BSD", [], "MIT"),
    ("  ", "MIT", [], "MIT"),
    ("UNKNOWN", "MIT", [], "MIT"),
    (None, " UNKNOWN ", ["License :: OSI Approved :: MIT License"], "MIT License"),
    (None, "  ", ["License :: OSI Approved :: Apache Software License"], "Apache Software License"),
    (None, "x" * 161, ["License :: OSI Approved :: MIT License"], "MIT License"),
    (None, "x" * 161, [], "UNKNOWN"),
    (" UNKNOWN ", " unknown ", [], "UNKNOWN"),
    (None, None, [], "UNKNOWN"),
    (None, None, ["License :: OSI Approved"], "UNKNOWN"),
    (None, None, ["License :: Other/Proprietary License"], "Other/Proprietary License"),
])
def test_license_metadata_precedence_and_missing_evidence(expression, license_value, classifiers, expected):
    metadata = Message()
    if expression is not None:
        metadata["License-Expression"] = expression
    if license_value is not None:
        metadata["License"] = license_value
    for value in classifiers:
        metadata["Classifier"] = value
    assert _license_name(SimpleNamespace(metadata=metadata)) == expected


def test_license_text_remains_available_without_guessing_an_identifier(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    text = "A long published license declaration.\n" * 100
    (source / "LICENSE.txt").write_text(text)
    metadata = Message()
    metadata["Name"] = "example"
    metadata["License"] = text
    distribution = SimpleNamespace(metadata=metadata, version="1", files=["LICENSE.txt"],
                                   locate_file=lambda name: source / name)
    assert _license_name(distribution) == "UNKNOWN"
    destination = tmp_path / "release"
    copied = _copy_license_files(distribution, destination)
    assert len(copied) == 1
    assert (destination / copied[0]).read_text() == text
