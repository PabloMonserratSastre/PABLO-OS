"""Bundle local styles/scripts for an opaque-origin, authenticated static preview."""
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from .workspace_tools import _read, _relative, workspace_path


def preview_html(file):
    class Bundle(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.parts = []
            self.size = 0
            self.deferred = []
            self.skip_script = False

        def asset(self, url, suffix):
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or parsed.path.startswith('/'):
                raise ValueError("La vista previa necesita CSS y JavaScript locales.")
            target = workspace_path(_relative(file.parent) + '/' + unquote(parsed.path), existing=True)
            if not target.is_relative_to(file.parent) or target.suffix.lower() != suffix:
                raise ValueError("Los recursos deben estar dentro de la carpeta de la web.")
            content = _read(target)
            self.size += len(content.encode('utf-8'))
            if self.size > 1_000_000:
                raise ValueError("La vista previa admite hasta 1 MB de estilos y scripts.")
            return content

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == 'link' and values.get('rel', '').lower() == 'stylesheet' and values.get('href'):
                self.parts.append('<style>' + self.asset(values['href'], '.css').replace('</style', '<\\/style') + '</style>')
            elif tag == 'script' and values.get('src'):
                code = self.asset(values['src'], '.js').replace('</script', '<\\/script')
                if 'defer' in values or values.get('type') == 'module':
                    self.deferred.append(('<script type="module">' if values.get('type') == 'module' else '<script>') + code + '</script>')
                    self.skip_script = True
                else:
                    self.parts.append('<script>' + code)
            else:
                self.parts.append(self.get_starttag_text())

        def handle_endtag(self, tag):
            if tag == 'script' and self.skip_script:
                self.skip_script = False
                return
            self.parts.append('</' + tag + '>')
        def handle_data(self, data):
            if not self.skip_script: self.parts.append(data)
        def handle_entityref(self, name): self.parts.append('&' + name + ';')
        def handle_charref(self, name): self.parts.append('&#' + name + ';')
        def handle_decl(self, decl): self.parts.append('<!' + decl + '>')
        def handle_comment(self, data): self.parts.append('<!--' + data + '-->')

    parser = Bundle()
    parser.feed(_read(file))
    return ''.join(parser.parts) + ''.join(parser.deferred)
