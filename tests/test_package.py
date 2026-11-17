import llm_gates


def test_version_and_exports() -> None:
    assert llm_gates.__version__ == "0.1.0"
    for name in llm_gates.__all__:
        assert hasattr(llm_gates, name), name
