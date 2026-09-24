"""Media types, and the parameters they may carry."""

from schema_to.io.media_type import MediaType, MediaTypeParam, MediaTypes


def test_the_essence_is_the_type_and_subtype() -> None:
    assert MediaType("application", "json").essence == "application/json"


def test_a_type_without_parameters_reads_as_its_essence() -> None:
    assert MediaType("application", "json").string == "application/json"


def test_parameters_are_appended_in_order() -> None:
    media_type = MediaType(
        "text", "plain", (MediaTypeParam("charset", "utf-8"), MediaTypeParam("boundary", "x"))
    )
    assert media_type.string == "text/plain;charset=utf-8;boundary=x"


def test_a_media_type_prints_as_its_string() -> None:
    assert (
        str(MediaType("text", "plain", (MediaTypeParam("charset", "utf-8"),)))
        == "text/plain;charset=utf-8"
    )


def test_a_parameter_is_found_by_name() -> None:
    media_type = MediaType("text", "plain", (MediaTypeParam("charset", "utf-8"),))
    assert media_type.get_param_value("charset") == "utf-8"


def test_a_missing_parameter_falls_back_to_the_default() -> None:
    assert MediaType("text", "plain").get_param_value("charset", "utf-8") == "utf-8"


def test_a_missing_parameter_without_a_default_is_none() -> None:
    assert MediaType("text", "plain").get_param_value("charset") is None


def test_a_parameter_given_twice_with_one_value_is_unambiguous() -> None:
    media_type = MediaType(
        "text", "plain", (MediaTypeParam("charset", "utf-8"), MediaTypeParam("charset", "utf-8"))
    )
    assert media_type.get_param_value("charset") == "utf-8"


def test_a_parameter_given_two_values_falls_back_to_the_default() -> None:
    """Two different values means no single answer, so the caller's default stands."""
    media_type = MediaType(
        "text", "plain", (MediaTypeParam("charset", "utf-8"), MediaTypeParam("charset", "latin-1"))
    )
    assert media_type.get_param_value("charset", "utf-8") == "utf-8"


def test_every_value_of_a_repeated_parameter_is_kept_in_order() -> None:
    media_type = MediaType("text", "plain", (MediaTypeParam("q", "1"), MediaTypeParam("q", "2")))
    assert list(media_type.get_param_values("q")) == ["1", "2"]


def test_an_absent_parameter_has_no_values() -> None:
    assert list(MediaType("text", "plain").get_param_values("q")) == []


def test_media_types_with_the_same_parts_are_equal() -> None:
    """They are used as dictionary keys and in sets, so equality has to hold."""
    assert MediaType("application", "json") == MediaType("application", "json")
    assert len({MediaTypes.json, MediaType("application", "json")}) == 1
