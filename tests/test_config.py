import os
import pytest
from pydantic import ValidationError

from realtime_api.config import load_config

HERE = os.path.dirname(__file__)
MULTI = os.path.join(HERE, "test_config_multimodel.yaml")
LEGACY = os.path.join(HERE, "test_config.yaml")


def test_multimodel_config_loads_named_models():
    cfg = load_config(MULTI)
    names = [m.name for m in cfg.katago.models]
    assert names == ["b28", "b18"]
    assert cfg.katago.default_model == "b28"
    # per-model human_model present and resolved absolute
    b18 = next(m for m in cfg.katago.models if m.name == "b18")
    assert b18.human_model is not None
    assert os.path.isabs(b18.path)
    assert os.path.isabs(b18.human_model.path)


def test_default_model_mirrored_onto_legacy_fields():
    # legacy accessors keep working: .model / .human_model == the default (b28) model
    cfg = load_config(MULTI)
    b28 = next(m for m in cfg.katago.models if m.name == "b28")
    assert cfg.katago.model is not None
    assert cfg.katago.model.path == b28.path
    assert cfg.katago.human_model is not None
    assert cfg.katago.human_model.path == b28.human_model.path


def test_legacy_single_model_config_still_loads():
    cfg = load_config(LEGACY)
    assert [m.name for m in cfg.katago.models] == ["default"]
    assert cfg.katago.default_model == "default"
    assert cfg.katago.model is not None  # legacy accessor intact
    assert os.path.isabs(cfg.katago.models[0].path)


def test_default_model_must_name_an_existing_model(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "  default_model: nope\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_duplicate_model_names_rejected(tmp_path):
    bad = tmp_path / "dup.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "    - {name: b28, path: /tmp/b28b.bin.gz}\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_default_model_required_when_models_present(tmp_path):
    # models[] given but default_model omitted → reject (no silent first-element pick).
    bad = tmp_path / "nodefault.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "    - {name: b18, path: /tmp/b18.bin.gz}\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_mixed_legacy_and_models_rejected(tmp_path):
    # supplying BOTH models[] and a legacy model: is ambiguous → reject.
    bad = tmp_path / "mixed.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  model: {path: /tmp/legacy.bin.gz}\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_mixed_legacy_human_model_and_models_rejected(tmp_path):
    # models[] combined with a legacy top-level human_model: is also ambiguous → reject
    # (this is the case an after-only validator would silently overwrite).
    bad = tmp_path / "mixed_human.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  human_model: {path: /tmp/legacy-human.bin.gz}\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_empty_models_list_rejected(tmp_path):
    # An explicit empty models: [] is a malformed/partial config → reject (an
    # after-validator would misread it as legacy form).
    bad = tmp_path / "empty_models.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models: []\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_per_model_additional_args_default_empty_and_parsed(tmp_path):
    # per-model additional_args defaults to [] and is parsed when supplied.
    good = tmp_path / "extra.yaml"
    good.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - name: b28\n"
        "      path: /tmp/b28.bin.gz\n"
        "      sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n"
        "    - name: b18\n"
        "      path: /tmp/b18.bin.gz\n"
        "      sha256: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'\n"
        "      additional_args: ['-override-config', 'cudaDeviceToUseThread0=1']\n"
        "  default_model: b28\n"
    )
    cfg = load_config(str(good))
    b28 = next(m for m in cfg.katago.models if m.name == "b28")
    b18 = next(m for m in cfg.katago.models if m.name == "b18")
    assert b28.additional_args == []
    assert b18.additional_args == ["-override-config", "cudaDeviceToUseThread0=1"]


@pytest.mark.parametrize(
    "model_yaml",
    [
        "    - {name: b28, path: '', sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'}\n",
        "    - {name: b28, path: /tmp/b28.bin.gz}\n",
        "    - {name: b28, path: /tmp/b28.bin.gz, sha256: ''}\n",
        (
            "    - name: b28\n"
            "      path: /tmp/b28.bin.gz\n"
            "      sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n"
            "      human_model: {path: /tmp/human.bin.gz}\n"
        ),
    ],
)
def test_multimodel_requires_nonempty_paths_and_hashes(tmp_path, model_yaml):
    bad = tmp_path / "missing-identity.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        + model_yaml
        + "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


@pytest.mark.parametrize(
    "schema_body",
    [
        "  model: {path: /tmp/main.bin.gz, sha256: short}\n",
        "  model: {path: /tmp/main.bin.gz, sha256: 'gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg'}\n",
        (
            "  model: {path: /tmp/main.bin.gz, sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'}\n"
            "  human_model: {path: /tmp/human.bin.gz, sha256: xyz}\n"
        ),
        (
            "  models:\n"
            "    - {name: b28, path: /tmp/main.bin.gz, sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!'}\n"
            "  default_model: b28\n"
        ),
    ],
)
def test_all_provided_model_hashes_must_be_64_hex_characters(tmp_path, schema_body):
    bad = tmp_path / "invalid-hash.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        + schema_body
    )
    with pytest.raises(ValidationError, match="64 hexadecimal"):
        load_config(str(bad))
