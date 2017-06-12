# coding: utf-8

from __future__ import unicode_literals

import bisect
import sys
from awpa.btm_matcher import BottomMatcher
from awpa import (
    decode_bytes_using_source_encoding,
    load_grammar,
    patcomp,
    read_file_using_source_encoding)

import attr
import flake8_polyfill.options
import flake8_polyfill.stdin
import pycodestyle
import six
from gather import Collector, Wrapper
from intervaltree import Interval


flake8_polyfill.stdin.monkey_patch('pycodestyle')


def current_python_grammar():
    grammar_name = 'py{0.major}{0.minor}'.format(sys.version_info)
    return load_grammar(grammar_name)


def fix_grammar_for_future_features(grammar, future_features):
    if 'print_function' in future_features and 'print' in grammar.keywords:
        grammar_old = grammar
        grammar = grammar.copy()
        # XXX: put this in awpa
        grammar.token, grammar.start, grammar.symbols = grammar_old.token, grammar_old.start, grammar_old.symbols
        del grammar.keywords['print']
    return grammar


@attr.s
class Lines(object):
    lines = attr.ib()
    last_pos = attr.ib()
    last_byte = attr.ib()

    @classmethod
    def from_line_iterator(cls, line_iter):
        count = 0
        lines = [(0, '')]
        for line in line_iter:
            lines.append((count, line))
            count += len(line)
        last_pos = len(lines) - 1, len(lines[-1][1])
        return cls(lines=lines, last_pos=last_pos, last_byte=count)

    def __getitem__(self, idx):
        return self.lines[idx]

    def __iter__(self):
        for e, (count, line) in enumerate(self.lines):
            if e == 0:
                continue
            yield e, count, line

    def position_of_byte(self, byte):
        lineno = bisect.bisect_left(self.lines, (byte + 1,)) - 1
        column = byte - self.lines[lineno][0]
        return lineno, column

    def byte_of_pos(self, lineno, column):
        # This requires a bit of explanation. The source passed to lib2to3's
        # parser has an extra newline added in some cases, to deal with a bug
        # in lib2to3 where it crashes hard if files don't end with a trailing
        # newline. When that extra line is added, the final DEDENT token in the
        # file will have a lineno equal to the lines in the file plus one,
        # becase it's "at" a location that doesn't exist in the real file. If
        # this case wasn't specifically caught, the self[lineno] would raise an
        # exception because lineno is beyond the last index in self.lines. So,
        # when that case is detected, return the final byte position.
        if lineno == len(self.lines) and column == 0:
            return self.last_byte
        byte, _ = self[lineno]
        byte += column
        return byte

    def byte_of_node(self, node):
        return self.byte_of_pos(node.lineno, node.column)


@attr.s
class Source(object):
    text = attr.ib()
    lines = attr.ib()
    filename = attr.ib()

    @classmethod
    def from_filename(cls, filename):
        if filename != 'stdin':
            source = read_file_using_source_encoding(filename)
        elif six.PY2:  # ✘py3
            # On python 2, reading from stdin gives you bytes, which must
            # be decoded.
            source = decode_bytes_using_source_encoding(
                pycodestyle.stdin_get_value())
        else:  # ✘py2
            # On python 3, reading from stdin gives you text.
            source = pycodestyle.stdin_get_value()

        return cls.from_text(source, filename=filename)

    @classmethod
    def from_text(cls, text, filename=None):
        lines = Lines.from_line_iterator(text.splitlines(True))
        return cls(text=text, lines=lines, filename=filename)

    def message_for_node(self, node, error, **kw):
        line_offset = kw.pop('line_offset', None)
        if line_offset is None:
            byte = self.lines.byte_of_node(node) + kw.pop('offset', 0)
            lineno, column = self.lines.position_of_byte(byte)
        else:
            lineno = node.lineno + line_offset
            column = kw.pop('column')
        return self.message_for_pos((lineno, column), error, **kw)

    def message_for_pos(self, pos, error, **kw):
        lineno, column = pos
        message = '{}{} {}'.format(
            error._prefix, error.value.code, error.value.message.format(**kw))
        # XXX: what should this type be
        return lineno, column, message, type(None)

    def as_tokens(self, grammar, base_byte=0):
        for typ, tok, spos, epos, _ in grammar.generate_tokens(self.text):
            yield typ, tok, Interval(
                self.lines.byte_of_pos(*spos) + base_byte,
                self.lines.byte_of_pos(*epos) + base_byte)


@attr.s
class ParsedSource(object):
    source = attr.ib()
    future_features = attr.ib()
    tree = attr.ib()
    had_trailing_newline = attr.ib()


def byte_intersection(tree, lower, upper):
    ret = 0
    for i in tree.search(lower, upper):
        ret += min(i.end, upper) - max(i.begin, lower)
    return ret


@attr.s(cmp=False, frozen=True)
class CheckerConfig(object):
    string_pattern = attr.ib()
    extra = attr.ib()


@attr.s(cmp=False, frozen=True)
class CollectedChecker(object):
    config = attr.ib()
    function = attr.ib()
    pattern = attr.ib()
    tree = attr.ib()


@attr.s
class Collected(object):
    grammar = attr.ib()
    pysyms = attr.ib()
    matcher = attr.ib()
    checkers = attr.ib()

    @classmethod
    def from_grammar_name(cls, grammar_name):
        _, grammar, pysyms = load_grammar(grammar_name)
        matcher = BottomMatcher(grammar)
        return cls(grammar=grammar, pysyms=pysyms, matcher=matcher, checkers=[])

    def gather_checkers(self, collector):
        all_new_checkers = collector.collect(strategy=Collector.all)
        for new_checkers in six.itervalues(all_new_checkers):
            for wrapper in new_checkers:
                pattern, tree = patcomp.compile_pattern(
                    self.grammar, wrapper.extra.string_pattern, with_tree=True)
                self.matcher.add_pattern_by_key(tree, len(self.checkers))
                self.checkers.append(CollectedChecker(
                    config=wrapper.extra, function=wrapper.original,
                    pattern=pattern, tree=tree))

    def parse_source(self, source):
        future_features = self.grammar.detect_future_features(source.text)
        grammar = fix_grammar_for_future_features(self.grammar, future_features)
        tree, trailing_newline = grammar.parse_source(source.text)
        return ParsedSource(
            source=source, future_features=future_features, tree=tree,
            had_trailing_newline=trailing_newline)

    def check_parsed(self, parsed):
        for error in self._check_tree(parsed):
            yield error

    def _check_tree(self, parsed):
        matches = self.matcher.run(parsed.tree.pre_order())
        node_matches = {}
        for checker_idx, nodes in six.iteritems(matches):
            for node in nodes:
                node_matches.setdefault(id(node), set()).add(checker_idx)

        for node in parsed.tree.pre_order():
            for checker_idx in node_matches.get(id(node), ()):
                checker = self.checkers[checker_idx]
                results = {}
                if not checker.pattern.match(node, results):
                    continue
                extra = checker.config.extra
                for k in extra.get('comments_for', ()):
                    # XXX: this doesn't use `k` for finding the node; `k` is
                    # supposed to name a specific node, but it isn't used when
                    # choosing which node is added to results.
                    results[k + '_comments'] = [
                        c for c, i in self.find_comments(node.prefix)]
                if extra.get('pass_filename', False):
                    results['filename'] = parsed.source.filename
                if extra.get('pass_future_features', False):
                    results['future_features'] = parsed.future_features
                if extra.get('pass_grammar', False):
                    results['grammar'] = self.grammar
                for error_node, error, kw in checker.function(**results):
                    yield parsed.source.message_for_node(error_node, error, **kw)

    def find_comments(self, source, base_byte=0):
        source = Source.from_text(six.text_type(source).rstrip(' \t\r\n\\'))
        for typ, tok, interval in source.as_tokens(self.grammar, base_byte=base_byte):
            if typ == self.grammar.token.COMMENT:
                yield tok, interval


def make_collector(name):
    collector = Collector(name=name)

    def register_checker(pattern, **extra):
        usable = not (
            ('python_minimum_version' in extra
             and sys.version_info < extra['python_minimum_version'])
            or
            ('python_disabled_version' in extra
             and sys.version_info > extra['python_disabled_version']))

        if usable:
            config = CheckerConfig(string_pattern=pattern, extra=extra)
            deco = collector.register(transform=Wrapper.glue(config))
        else:
            def deco(f):
                return f

        return deco

    return collector, register_checker
