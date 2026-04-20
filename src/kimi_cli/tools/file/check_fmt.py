import asyncio
import xml.etree.ElementTree as ET
import json
from typing import Callable, Any


def check_json_text(text: str, json_callback: Callable[[Any], None] | None = None) -> str | None:
    """Validate the format of a JSON string.

    Args:
        text: JSON text to validate.
        json_callback: Optional callback invoked with the parsed object.

    Returns:
        None if the JSON is valid, error message string otherwise.
    """
    try:
        js = json.loads(text)
        if json_callback is not None:
            json_callback(js)
        return None
    except json.JSONDecodeError as exc:
        return f"JSON decode error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except Exception as exc:
        return f"failed to validate JSON file: {str(exc)}"


async def check_json(file_path: str, json_callback: Callable[[Any], None] | None = None) -> str | None:
    """Validate the format of a JSON file.

    Args:
        file_path: Path to the JSON file to validate.

    Returns:
        None if the JSON file is valid, error message string otherwise.
    """
    def _check() -> str | None:
        with open(file_path, 'r', encoding='utf-8') as f:
            js = json.load(f)
        if json_callback is not None:
            json_callback(js)
        return None

    try:
        return await asyncio.to_thread(_check)

    except json.JSONDecodeError as exc:
        return f"JSON decode error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except Exception as exc:
        return f"failed to validate JSON file: {str(exc)}"


def check_xml_text(text: str, xml_callback: Callable[[Any], None] | None = None) -> str | None:
    """Validate the format of an XML string.

    Args:
        text: XML text to validate.
        xml_callback: Optional callback invoked with the parsed tree.

    Returns:
        None if the XML is valid, error message string otherwise.
    """
    try:
        tree = ET.fromstring(text)
        if xml_callback is not None:
            xml_callback(tree)
        return None
    except ET.ParseError as exc:
        return f"XML parse error: {str(exc)}"
    except Exception as exc:
        return f"failed to validate XML file: {str(exc)}"


async def check_xml(file_path: str, xml_callback: Callable[[Any], None] | None = None) -> str | None:
    """Validate the format of an XML file.

    Args:
        file_path: Path to the XML file to validate.

    Returns:
        None if the XML file is valid, error message string otherwise.
    """
    def _check() -> str | None:
        tree = ET.parse(file_path)
        if xml_callback is not None:
            xml_callback(tree)
        return None

    try:
        return await asyncio.to_thread(_check)

    except ET.ParseError as exc:
        return f"XML parse error: {str(exc)}"
    except Exception as exc:
        return f"failed to validate XML file: {str(exc)}"
