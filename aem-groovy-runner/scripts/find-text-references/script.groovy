import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import org.apache.sling.api.resource.Resource

// Find where a piece of text (a tracking domain, script URL, ID) appears under
// a path, both inside file contents (clientlib JS, HTL, CSS, JSON stored as
// nt:file) and in string properties of any node.
// AEM's full-text search doesn't cover file contents under /apps, which is
// why this walks the tree instead of querying. A tree walk reads every node
// under the path: use it on /apps/<project>, /conf/<site> or a site subtree.

// INPUT: injected by AEM Groovy Runner from manifest.json inputs.
def CONFIG = new JsonSlurper().parseText(new String("__CONFIG_B64__".decodeBase64(), "UTF-8"))

def rootPath = CONFIG.rootPath as String
def needle = ((CONFIG.text ?: "") as String).trim()
def lowerNeedle = needle.toLowerCase()
def extensions = ((CONFIG.fileExtensions ?: []) as List<String>).collect { it.trim().toLowerCase() }.findAll { it }
if (!extensions) {
    extensions = [".js", ".html", ".css", ".json", ".jsp", ".txt", ".xml"]
}
def maxResults = (CONFIG.maxResults ?: 0) as int
def excludedPaths = (CONFIG.excludedPaths ?: []) as List<String>
def maxFileBytes = 2_000_000  // larger files are skipped and counted

def emit = { Map payload ->
    println "===GROOVY_RUNNER_JSON_START==="
    println JsonOutput.toJson(payload)
    println "===GROOVY_RUNNER_JSON_END==="
}

if (!needle) {
    emit([error: "Enter the text to find", rows: []])
    return
}
def root = resourceResolver.getResource(rootPath)
if (!root) {
    emit([error: "Path not found: ${rootPath}".toString(), rows: []])
    return
}

def isExcludedPath = { String path -> excludedPaths.any { ex -> path == ex || path.startsWith(ex + "/") } }

// Up to 80 characters either side of the first match, on one line.
def snippetOf = { String value ->
    def at = value.toLowerCase().indexOf(lowerNeedle)
    def from = Math.max(0, at - 80)
    def to = Math.min(value.length(), at + lowerNeedle.length() + 80)
    (from > 0 ? "..." : "") + value.substring(from, to).replaceAll(/\s+/, " ").trim() + (to < value.length() ? "..." : "")
}

def rows = []
def counts = [nodesRead: 0, filesRead: 0, skippedLargeFiles: 0]
def truncated = false

def addRow = { Map row ->
    if (maxResults > 0 && rows.size() >= maxResults) {
        truncated = true
        return
    }
    rows << row
}

def fileText = { Resource file ->
    def data = file.getChild("jcr:content")?.getValueMap()?.get("jcr:data", InputStream)
    if (data == null) {
        return null
    }
    def bytes = data.withStream { it.readNBytes(maxFileBytes + 1) }
    if (bytes.length > maxFileBytes) {
        counts.skippedLargeFiles++
        return null
    }
    new String(bytes, "UTF-8")
}

// Depth-first walk with an explicit stack, so deep trees can't overflow.
def pending = new ArrayDeque<Resource>()
pending.addFirst(root)
while (!pending.isEmpty() && !truncated) {
    def resource = pending.removeFirst()
    def path = resource.getPath()
    if (isExcludedPath(path)) {
        continue
    }
    counts.nodesRead++
    def props = resource.getValueMap()

    if (props.get("jcr:primaryType", "") == "nt:file") {
        def name = resource.getName().toLowerCase()
        if (extensions.any { name.endsWith(it) }) {
            def text = fileText(resource)
            if (text != null) {
                counts.filesRead++
                text.readLines().eachWithIndex { line, index ->
                    if (line.toLowerCase().contains(lowerNeedle)) {
                        addRow(["Path": path, "Where": "File content", "Property": "", "Line": index + 1, "Snippet": snippetOf(line)])
                    }
                }
            }
        }
        continue  // a file's jcr:content only holds its binary data
    }

    props.each { key, value ->
        def values = value instanceof Object[] ? (value as List) : [value]
        values.each { item ->
            if (item instanceof String && item.toLowerCase().contains(lowerNeedle)) {
                addRow(["Path": path, "Where": "Property", "Property": key, "Line": "", "Snippet": snippetOf(item)])
            }
        }
    }
    // Reverse so children are visited in their natural order.
    resource.listChildren().toList().reverse().each { pending.addFirst(it) }
}

emit([rows: rows, text: needle, rootPath: rootPath, truncated: truncated] + counts)
