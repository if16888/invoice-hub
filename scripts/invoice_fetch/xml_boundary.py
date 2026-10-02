"""Encoding-independent, bounded XML parsing for untrusted invoice inputs."""

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException


MAX_XML_BYTES = 2 * 1024 * 1024


def parse_invoice_xml(data: bytes):
    """Reject DTDs and all entity declarations before building an XML tree.

    Parser-level restrictions apply regardless of the document's encoding.
    Never include untrusted XML or exception details in the public error.
    """
    if len(data) > MAX_XML_BYTES:
        raise ValueError("XML 发票超过大小限制")
    try:
        return ElementTree.fromstring(
            data, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except (DefusedXmlException, ElementTree.ParseError, ValueError) as exc:
        raise ValueError("XML 发票内容不受支持") from exc
