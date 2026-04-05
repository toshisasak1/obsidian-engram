from engram.config import EngramConfig, discover_sources, generate_config_toml


def test_default_config():
    config = EngramConfig()
    assert config.search.rrf_k == 60
    assert config.search.half_life_days == 30.0
    assert config.embedding.enabled is False

def test_generate_config_toml():
    config = EngramConfig()
    toml_str = generate_config_toml(config)
    assert "[search]" in toml_str
    assert "rrf_k" in toml_str

def test_discover_sources():
    sources = discover_sources()
    # Just verify it returns a dict without crashing
    assert isinstance(sources, dict)
