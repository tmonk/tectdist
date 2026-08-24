"""Manifest validation that works without a third-party JSON-schema package."""
from pathlib import Path

REQUIRED = {
    "id", "path", "main", "license", "claim", "platforms", "scenarios",
    "expected_pages", "expected_text", "engine", "requires",
    "requires_bibliography", "requires_index", "requires_glossary", "requires_shell_escape",
    "edit_operations",
}


def validate(data, root):
    errors = []
    identifiers = set()
    for document in data.get("document", []):
        missing = REQUIRED - set(document)
        if missing:
            errors.append("%s: missing %s" % (document.get("id", "<unknown>"), ", ".join(sorted(missing))))
            continue
        identifier = document["id"]
        if identifier in identifiers:
            errors.append("duplicate id: " + identifier)
        identifiers.add(identifier)
        source = Path(root) / document["path"] / document["main"]
        if not source.is_file():
            errors.append("%s: missing source %s" % (identifier, source))
        if not document["scenarios"]:
            errors.append("%s: no scenarios" % identifier)
        if document["engine"] != "tectonic":
            errors.append("%s: unsupported declared engine" % identifier)
        if not isinstance(document["requires"], list):
            errors.append("%s: requires must be a list" % identifier)
        if not isinstance(document["edit_operations"], list):
            errors.append("%s: edit_operations must be a list" % identifier)
        if not isinstance(document["requires_bibliography"], bool):
            errors.append("%s: requires_bibliography must be a boolean" % identifier)
        if not isinstance(document["requires_index"], bool):
            errors.append("%s: requires_index must be a boolean" % identifier)
        if not isinstance(document["requires_glossary"], bool):
            errors.append("%s: requires_glossary must be a boolean" % identifier)
        if not isinstance(document["requires_shell_escape"], bool):
            errors.append("%s: requires_shell_escape must be a boolean" % identifier)
        if "bibliography" in document["scenarios"] and not document["requires_bibliography"]:
            errors.append("%s: bibliography scenario requires requires_bibliography" % identifier)
        if "index" in document["scenarios"] and not document["requires_index"]:
            errors.append("%s: index scenario requires requires_index" % identifier)
    # The intentionally bounded corpus has one fixture for each documented
    # feature class. Do not turn this into a download-count requirement.
    if data.get("corpus_kind", "core") == "core" and len(identifiers) < 12:
        errors.append("benchmark corpus requires the 12 documented workload classes")
    return errors
