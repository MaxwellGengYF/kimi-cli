import xml.etree.ElementTree as ET
import orjson
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
        js = orjson.loads(text)
        if json_callback is not None:
            json_callback(js)
        return None
    except orjson.JSONDecodeError as exc:
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

