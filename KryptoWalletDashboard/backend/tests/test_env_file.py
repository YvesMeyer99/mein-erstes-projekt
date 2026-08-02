import pytest

from app.env_file import CONFIG_FIELDS, InvalidConfigValueError, read_config_values, write_config_values


def _write(path, content):
    path.write_text(content, encoding="utf-8")


def test_read_config_values_returns_value_for_known_field(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc123\n")

    values = read_config_values(str(env_file))

    assert values["SOLANA_ADDRESSES"] == "main:abc123"


def test_read_config_values_returns_empty_string_for_missing_field(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc123\n")

    values = read_config_values(str(env_file))

    assert values["VECHAIN_ADDRESSES"] == ""


def test_read_config_values_never_returns_a_real_secret(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "KRAKEN_API_SECRET=super-secret-value\n")

    values = read_config_values(str(env_file))

    assert values["KRAKEN_API_SECRET"] == ""


def test_read_config_values_covers_every_known_field_even_for_missing_file(tmp_path):
    env_file = tmp_path / "does-not-exist.env"

    values = read_config_values(str(env_file))

    assert set(values) == {f.name for f in CONFIG_FIELDS}
    assert all(v == "" for v in values.values())


def test_read_config_values_ignores_comments_and_blank_lines(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "# comment\n\nSOLANA_ADDRESSES=main:abc123\n")

    values = read_config_values(str(env_file))

    assert values["SOLANA_ADDRESSES"] == "main:abc123"


def test_write_config_values_replaces_existing_line_in_place(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "# keep me\nSOLANA_ADDRESSES=old\nVECHAIN_ADDRESSES=unrelated\n")

    write_config_values({"SOLANA_ADDRESSES": "new"}, str(env_file))

    content = env_file.read_text(encoding="utf-8")
    assert "SOLANA_ADDRESSES=new" in content
    assert "# keep me" in content
    assert "VECHAIN_ADDRESSES=unrelated" in content
    assert "SOLANA_ADDRESSES=old" not in content


def test_write_config_values_appends_field_not_yet_present(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc\n")

    write_config_values({"VECHAIN_ADDRESSES": "main:0xabc"}, str(env_file))

    content = env_file.read_text(encoding="utf-8")
    assert "VECHAIN_ADDRESSES=main:0xabc" in content
    assert "SOLANA_ADDRESSES=main:abc" in content


def test_write_config_values_creates_file_if_missing(tmp_path):
    env_file = tmp_path / ".env"

    write_config_values({"SOLANA_ADDRESSES": "main:abc"}, str(env_file))

    assert env_file.read_text(encoding="utf-8").strip() == "SOLANA_ADDRESSES=main:abc"


def test_write_config_values_leaves_existing_secret_untouched_when_value_is_empty(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "KRAKEN_API_SECRET=existing-secret\n")

    write_config_values({"KRAKEN_API_SECRET": ""}, str(env_file))

    assert "KRAKEN_API_SECRET=existing-secret" in env_file.read_text(encoding="utf-8")


def test_write_config_values_overwrites_secret_when_non_empty_value_given(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "KRAKEN_API_SECRET=old-secret\n")

    write_config_values({"KRAKEN_API_SECRET": "new-secret"}, str(env_file))

    content = env_file.read_text(encoding="utf-8")
    assert "KRAKEN_API_SECRET=new-secret" in content
    assert "old-secret" not in content


def test_write_config_values_clears_non_secret_field_when_empty_value_given(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "VECHAIN_ADDRESSES=main:0xabc\n")

    write_config_values({"VECHAIN_ADDRESSES": ""}, str(env_file))

    content = env_file.read_text(encoding="utf-8")
    assert "VECHAIN_ADDRESSES=\n" in content
    assert "0xabc" not in content


def test_write_config_values_does_nothing_for_empty_updates_dict(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc\n")

    write_config_values({}, str(env_file))

    assert env_file.read_text(encoding="utf-8") == "SOLANA_ADDRESSES=main:abc\n"


def test_write_config_values_rejects_unknown_field_name(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc\n")

    with pytest.raises(InvalidConfigValueError):
        write_config_values({"NOT_A_REAL_FIELD": "value"}, str(env_file))

    # Nothing must have been written -- validation happens before any I/O.
    assert env_file.read_text(encoding="utf-8") == "SOLANA_ADDRESSES=main:abc\n"


def test_write_config_values_rejects_value_containing_newline(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "KRAKEN_API_KEY=real-key\n")

    with pytest.raises(InvalidConfigValueError):
        write_config_values(
            {"BITCOIN_ADDRESSES": "x\nKRAKEN_API_KEY=injected"}, str(env_file)
        )

    content = env_file.read_text(encoding="utf-8")
    assert content == "KRAKEN_API_KEY=real-key\n"
    assert "injected" not in content


def test_write_config_values_rejects_value_containing_carriage_return(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc\n")

    with pytest.raises(InvalidConfigValueError):
        write_config_values({"SOLANA_ADDRESSES": "main:abc\rEVIL=1"}, str(env_file))

    assert env_file.read_text(encoding="utf-8") == "SOLANA_ADDRESSES=main:abc\n"


def test_write_config_values_still_accepts_a_normal_multi_field_update(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=old\nKRAKEN_API_KEY=old-key\n")

    write_config_values(
        {"SOLANA_ADDRESSES": "main:new", "KRAKEN_API_KEY": "new-key", "VECHAIN_ADDRESSES": "main:0xabc"},
        str(env_file),
    )

    content = env_file.read_text(encoding="utf-8")
    assert "SOLANA_ADDRESSES=main:new" in content
    assert "KRAKEN_API_KEY=new-key" in content
    assert "VECHAIN_ADDRESSES=main:0xabc" in content


def test_config_fields_all_have_a_name_section_and_label():
    for field in CONFIG_FIELDS:
        assert field.name
        assert field.section
        assert field.label


def test_config_fields_names_are_unique():
    names = [f.name for f in CONFIG_FIELDS]
    assert len(names) == len(set(names))
