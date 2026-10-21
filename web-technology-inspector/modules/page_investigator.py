"""Read-only investigation of retrieved AEM page content."""

from collections import deque


def normalize(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def search_properties(
    data,
    search_term,
    mode="Contains",
    case_sensitive=False,
    max_depth=20,
    max_nodes=5000,
    max_results=500,
):
    """Search page properties and nested component nodes."""

    if not search_term:
        return []

    matches = []
    queue = deque([(data, "", 0, None)])
    visited = 0

    def matches_term(value):
        value = normalize(value)
        term = search_term

        if not case_sensitive:
            value = value.lower()
            term = term.lower()

        if mode == "Exact":
            return value == term

        return term in value

    while queue and visited < max_nodes:
        node, path, depth, inherited_type = queue.popleft()
        visited += 1

        if depth > max_depth:
            continue

        if isinstance(node, dict):
            resource_type = node.get(
                "sling:resourceType",
                inherited_type
            )

            for key, value in node.items():
                current = path + "/" + key

                if isinstance(value, (dict, list)):
                    queue.append((
                        value,
                        current,
                        depth + 1,
                        resource_type
                    ))
                    continue

                values = (
                    value if isinstance(value, tuple)
                    else [value]
                )

                for item in values:
                    if (
                        matches_term(key)
                        or matches_term(item)
                    ):
                        if path == "/jcr:content":
                            source = "Page Properties"
                        elif path.startswith(
                            "/jcr:content/"
                        ):
                            source = "Component / Child Node"
                        else:
                            source = "Page Node / Other"

                        matches.append({
                            "node_path": path or "/",
                            "property": key,
                            "value": normalize(item)[:1000],
                            "resource_type": resource_type or "",
                            "source": source,
                            "matched_on": (
                                "property name"
                                if matches_term(key)
                                else "property value"
                            )
                        })

                        if len(matches) >= max_results:
                            return matches

        elif isinstance(node, list):
            for index, item in enumerate(node):
                queue.append((
                    item,
                    path + "/" + str(index),
                    depth + 1,
                    inherited_type
                ))

    return matches


def page_summary(data):
    """Return available page-level metadata."""

    content = data.get("jcr:content", {})

    if not isinstance(content, dict):
        content = {}

    fields = [
        "jcr:title",
        "jcr:description",
        "sling:resourceType",
        "cq:template",
        "cq:tags",
        "cq:lastModified",
        "cq:lastModifiedBy",
        "jcr:created",
        "jcr:createdBy"
    ]

    return {
        key: content.get(key)
        for key in fields
        if key in content
    }


def dialog_candidates(match):
    """Suggest possible Granite UI field locations.

    These are hints, not verified dialog definitions.
    """

    prop = match.get("property", "")
    resource_type = match.get("resource_type", "")

    return {
        "property": prop,
        "field_name": "./" + prop,
        "resource_type": resource_type,
        "likely_dialog": (
            "Page Properties"
            if match.get("source") == "Page Properties"
            else "Component Dialog / Configuration"
        ),
        "verified": False
    }
