"""Read-only mapping of property names to supplied Granite UI dialog JSON."""
from collections import deque

def locate_fields(dialog_json, property_name, max_nodes=3000):
    if not isinstance(dialog_json, (dict, list)):
        return []
    sought = {property_name, "./" + property_name}
    queue = deque([(dialog_json, "")])
    found = []
    count = 0
    while queue and count < max_nodes:
        node, path = queue.popleft()
        count += 1
        if isinstance(node, dict):
            if node.get("name") in sought:
                found.append({"dialog_node": path or "/", "field_name": node.get("name"),
                              "label": node.get("fieldLabel", ""),
                              "resource_type": node.get("sling:resourceType", ""),
                              "verified_in_supplied_definition": True})
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    queue.append((v, path + "/" + k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, (dict, list)):
                    queue.append((v, path + "/" + str(i)))
    return found
