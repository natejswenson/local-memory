"""Small concrete-syntax JSONC editor: duplicate keys refused, untouched bytes retained."""
from dataclasses import dataclass, field
import json
import re

TOKEN = re.compile(r'\s+|//[^\n]*(?:\n|$)|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null|[{}\[\],:]')


@dataclass
class Node:
    start: int
    end: int
    value: object
    children: dict = field(default_factory=dict)
    pairs: list = field(default_factory=list)
    trailing: bool = False


class Document:
    def __init__(self, text):
        self.text = text
        self.tokens = []
        end = 0
        for match in TOKEN.finditer(text):
            if match.start() != end: raise ValueError('INVALID_JSONC_TOKEN')
            end = match.end(); token = match.group()
            if token.isspace() or token.startswith(('//', '/*')): continue
            self.tokens.append((token, match.start(), end))
        if end != len(text): raise ValueError('INVALID_JSONC_TOKEN')
        self.position = 0
        self.root = self.parse()
        if self.position != len(self.tokens) or not isinstance(self.root.value, dict):
            raise ValueError('JSONC_OBJECT_REQUIRED')

    def take(self, expected=None):
        if self.position >= len(self.tokens): raise ValueError('INCOMPLETE_JSONC')
        item = self.tokens[self.position]; self.position += 1
        if expected and item[0] != expected: raise ValueError('INVALID_JSONC_STRUCTURE')
        return item

    def peek(self):
        return self.tokens[self.position][0] if self.position < len(self.tokens) else None

    def parse(self):
        token, start, end = self.take()
        if token == '{':
            result = Node(start, end, {})
            while self.peek() != '}':
                key, key_start, _ = self.take()
                if not key.startswith('"'): raise ValueError('JSONC_KEY_REQUIRED')
                key = json.loads(key)
                if key in result.children: raise ValueError('DUPLICATE_JSONC_KEY')
                self.take(':'); child = self.parse()
                result.children[key] = child; result.value[key] = child.value
                comma = self.take(',') if self.peek() == ',' else None
                result.pairs.append((key, key_start, child.end, comma))
                result.trailing = comma is not None
                if comma is None: break
            result.end = self.take('}')[2]
            return result
        if token == '[':
            values = []
            while self.peek() != ']':
                values.append(self.parse().value)
                if self.peek() != ',': break
                self.take(',')
            return Node(start, self.take(']')[2], values)
        try: value = json.loads(token)
        except json.JSONDecodeError as error: raise ValueError('INVALID_JSONC_VALUE') from error
        return Node(start, end, value)

    def set(self, keys, value):
        node = self.root
        for i, key in enumerate(keys):
            if not isinstance(node.value, dict): raise ValueError('JSONC_PARENT_NOT_OBJECT')
            if key not in node.children:
                nested = value
                for component in reversed(keys[i + 1:]): nested = {component: nested}
                prefix = '' if not node.children or node.trailing else ','
                addition = '\n' + prefix + json.dumps(key) + ': ' + json.dumps(nested, ensure_ascii=False, indent=2) + '\n'
                output = self.text[:node.end - 1] + addition + self.text[node.end - 1:]
                Document(output)
                return output
            node = node.children[key]
        output = self.text[:node.start] + json.dumps(value, ensure_ascii=False, indent=2) + self.text[node.end:]
        Document(output)
        return output

    def remove(self, keys):
        node = self.root
        for key in keys[:-1]:
            if key not in node.children: return self.text
            node = node.children[key]
        if keys[-1] not in node.children: return self.text
        for i, (key, start, end, comma) in enumerate(node.pairs):
            if key != keys[-1]: continue
            if comma: end = comma[2]
            elif i: start = node.pairs[i-1][3][1]
            output = self.text[:start] + self.text[end:]
            Document(output)
            return output
