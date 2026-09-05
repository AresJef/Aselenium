"""Strict runtime validation for values returned by WebDriver commands."""

from __future__ import annotations

from typing import TypeVar, cast

from aselenium import errors

T = TypeVar("T")


def typed_value(value: object, expected_type: type[T], description: str) -> T:
    """Require a runtime value to have exactly the documented broad type.

    Boolean values are rejected when an integer is expected because ``bool``
    is an ``int`` subclass but is not a valid numeric browser dimension.

    Args:
        value: Candidate value returned by a driver or injected script.
        expected_type: Required runtime type.
        description: Short value name included in diagnostics.

    Returns:
        The validated value.

    Raises:
        errors.InvalidResponseError: The value has the wrong runtime type.
    """
    matches = (
        type(value) is int if expected_type is int else isinstance(value, expected_type)
    )
    if not matches:
        raise errors.InvalidResponseError(
            f"{description} must be {expected_type.__name__}, "
            f"not {type(value).__name__}"
        )
    return cast(T, value)


def response_value(response: object, expected_type: type[T], description: str) -> T:
    """Extract and validate the ``value`` member of a W3C response envelope.

    Args:
        response: Candidate W3C response envelope.
        expected_type: Required runtime type for the ``value`` member.
        description: Short result name included in diagnostics.

    Returns:
        The validated response value.

    Raises:
        errors.InvalidResponseError: The response has no ``value`` member or
            the member has the wrong runtime type.
    """
    if not isinstance(response, dict) or "value" not in response:
        raise errors.InvalidResponseError(
            f"{description} response must contain a value"
        )
    return typed_value(
        response["value"], expected_type, f"{description} response value"
    )


def string_list(value: object, description: str) -> list[str]:
    """Validate a list whose every member is text.

    Args:
        value: Candidate list value.
        description: Short value name included in diagnostics.

    Returns:
        The validated string list.

    Raises:
        errors.InvalidResponseError: The value is not a list of strings.
    """
    result = typed_value(value, list, description)
    if not all(isinstance(item, str) for item in result):
        raise errors.InvalidResponseError(f"{description} must contain only strings")
    return result


def string_mapping(value: object, description: str) -> dict[str, str]:
    """Validate a mapping whose keys and values are text.

    Args:
        value: Candidate mapping value.
        description: Short value name included in diagnostics.

    Returns:
        The validated string mapping.

    Raises:
        errors.InvalidResponseError: The value is not a string-to-string mapping.
    """
    result = typed_value(value, dict, description)
    if not all(
        isinstance(key, str) and isinstance(item, str) for key, item in result.items()
    ):
        raise errors.InvalidResponseError(
            f"{description} must contain only string keys and values"
        )
    return result
