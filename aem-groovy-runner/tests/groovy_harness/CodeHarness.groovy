// /apps code fixture for find-text-references.
// Usage: CodeHarness <script>
import org.apache.sling.api.resource.*

class Res implements Resource {
    String path; Map props = [:]; Map<String, Res> children = [:]
    String getPath() { path }
    String getName() { path.tokenize('/').last() }
    Iterator<Resource> listChildren() { children.values().iterator() }
    Resource getChild(String rel) { def cur = this; for (seg in rel.split("/")) { cur = cur?.children?.get(seg) }; cur }
    def <T> T adaptTo(Class<T> t) { t == ValueMap ? (T) new SimpleValueMap(props) : null }
    ValueMap getValueMap() { new SimpleValueMap(props) }
}
def folder = { String p, List<Res> kids, Map props = ["jcr:primaryType": "sling:Folder"] ->
    new Res(path: p, props: props, children: kids.collectEntries { [(it.name): it] })
}
def file = { String p, byte[] data ->
    def content = new Res(path: p + "/jcr:content", props: ["jcr:primaryType": "nt:resource",
            "jcr:data": new ByteArrayInputStream(data)])
    new Res(path: p, props: ["jcr:primaryType": "nt:file"], children: ["jcr:content": content])
}
def text = { String p, String body -> file(p, body.getBytes("UTF-8")) }

def apps = folder("/apps/acme", [
    folder("/apps/acme/clientlibs", [
        text("/apps/acme/clientlibs/tracking.js", "(function () {\n  var u = 'x';\n  load('https://tracking.example.com/t.js');\n})();\n"),
        text("/apps/acme/clientlibs/site.css", "body { color: red; }\n"),
        file("/apps/acme/clientlibs/huge.js", ("// tracking.example.com\n" + "x".multiply(2_000_100)).getBytes("UTF-8")),
        file("/apps/acme/clientlibs/logo.png", "tracking.example.com".getBytes("UTF-8")),
    ]),
    folder("/apps/acme/components", [
        text("/apps/acme/components/customheaderlibs.html", "<head>\n<script src=\"https://TRACKING.Example.com/x.js\"></script>\n</head>\n"),
        new Res(path: "/apps/acme/components/embed", props: ["jcr:primaryType": "cq:Component",
                "defaultUrl": "https://tracking.example.com/pixel", "hosts": ["a.com", "x tracking.example.com"] as String[]]),
    ]),
    folder("/apps/acme/archive", [text("/apps/acme/archive/old.js", "tracking.example.com\n")]),
])
def resolver = [getResource: { String p -> p == "/apps/acme" ? apps : null }]
new GroovyShell(new Binding(resourceResolver: resolver)).evaluate(new File(args[0]).text)
