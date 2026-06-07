from pathlib import Path


def test_manifest_has_expected_provider_fields():
    text = Path('plugin.yaml').read_text(encoding='utf-8')
    assert 'name: mempalace' in text
    assert 'external_dependencies:' in text
    assert 'on_session_end' in text


def test_readme_documents_install_and_selection():
    text = Path('README.md').read_text(encoding='utf-8')
    assert 'hermes plugins install abdallah/hermes-mempalace --enable' in text
    assert 'hermes memory setup' in text
    assert 'mempalace' in text
