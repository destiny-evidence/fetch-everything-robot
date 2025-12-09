"""tests for fer/config.py."""

from fer.config import Settings


def test_get_settings(
    set_test_environment_variables: None, test_settings: Settings
) -> None:
    """
    Test the get_settings function.

    Args:
        set_test_environment_variables (None): Fixture to test environment variables.

    """
    expected_env = "test"
    expected_destiny_repository_url = "http://localhost:8001/enhancement/"
    expected_robot_id = "e0aba318-eee9-4b4c-b503-7f72547063d8"
    expected_robot_secret = "dummy_secret"  # noqa: S105 # pragma: allowlist secret
    expected_elsevier_scopus_key = "dummy_scopus_key"

    assert test_settings.env == expected_env
    assert (
        test_settings.destiny_repository_url.encoded_string()
        == expected_destiny_repository_url
    )
    assert str(test_settings.robot_id) == expected_robot_id
    assert test_settings.robot_secret == expected_robot_secret
    test_elsevier_scopus_key = (
        test_settings.elsevier_scopus_key.get_secret_value()
        if test_settings.elsevier_scopus_key
        else None
    )
    assert test_elsevier_scopus_key == expected_elsevier_scopus_key
