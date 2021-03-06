#!/usr/bin/python
# nomark python parser and html5/confluence render
# Copyright (C) 2013 Pablo Martin <pablo@odkq.com>
#
# This code is licensed under the GPLv3
#
from __future__ import print_function
import re
from cgi import escape
import sys
import csv
import json
import codecs
from string import join as sjoin
from cStringIO import StringIO
from pygments import highlight
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

from subprocess import Popen, PIPE, STDOUT

class Parser:
    ''' Nomark parser, converting text input into an array of paragraphs '''
    def __init__(self, filename):
        ''' Load the marktween in filename and parse it into a dictionary
            suitable for rendering '''
        self.pars = []
        self.links = {}
        self.retrieve_paragraphs(filename)

    def retrieve_paragraphs(self, filename):
        ''' Divide the text in paragraphs, separated by whitelines.
            As a special case, whitelines inside code blocks are allowed '''
        current = {'type': 'regular', 'text': ''}
        f = codecs.open(filename, encoding='utf-8', mode='r')
        for line in f.readlines():
            if current['type'] == 'code':
                if line[0] == u'.':
                    self.pars.append(current)
                    current = {'type': 'regular', 'text':''}
                else:
                    current['text'] += line.encode('utf8')
                continue
            if line[0] == u'.':
                current['type'] = 'code'
                if len(line) > 1:
                    l=line[1:].find('.')
                current['lang'] = line[1:l+1] if l != -1 else line[1:]
            elif line == '\n':
                if current['text'][0:2] == u'- ':
                    current['type'] = 'list'
                    current['text'] = current['text'][2:]
                self.pars.append(current)
                current = {'type': 'regular', 'text': ''}
            else:
                append = line.encode('utf8')[:-1] # Without \n
                if current['text'] == '':
                    current['text'] = append
                else:
                    current['text'] += ' ' + append
        self.pars = [self.parse_paragraph(par) for par in self.pars]

    def parse_paragraph(self, p):
        ''' Identify paragraphs as titles, with their level, as lists
            or tables and adjust the content of the array element
            with that '''
        # Check for titles
        level, title_string = self.get_title(p['text'])
        if level > 0:
            p['type'] = 'title'
            p['level'] = level
            p['text'] = title_string
            return p
        # Parse attributes
        if p['type'] in ['regular', 'list']:
            attribs, trimmed_string = self.parse_attributes(p['text'])
            #print 'attribs: ' + str(attribs) + ' trimmed_string: ' + \
            #      str(trimmed_string)
            p['text'] = trimmed_string
            p = dict(p.items() + attribs.items())    # Join dicts
        # Parse code with pygments
        pass    # TODO

        return p

    def parse_attributes(self, s):
        ''' Return a dictionary with {'bold': [[pos1, pos2], [pos1, pos2] ...,
            'underline': [[pos1, pos2], [pos1, pos2] ..., and the resulting
            string without the character markers '''
        o = ''
        underline = re.compile('\s_[^_]*_[\s|\.|;|:|,]')
        bold = re.compile('\s\*[^\*]*\*[\s|\.|;|:|,]')
        code = re.compile('\s\.[^\.]*\.[\s|\.|;|:|,]')
        link = re.compile('\s\[[^(\]|:)]*\][\s|\.|;|:|,|$]')
        href = re.compile('\s\[[^\]]*:[^\]]*\]')
        a = {'bold': [], 'underline': [], 'code': [], 'link': []}
        i = 0
        while True:
            if i >= len(s):
                break
            key_found = None
            if i == 0:
                check_string = ' ' + s[i:]  # Prepend ' ' for matching SOL
            else:
                check_string = s[i:]
            for regexp in [['underline', underline],
                           ['bold', bold],
                           ['code', code],
                           ['link', link],
                           ['href', href]]:
                match = regexp[1].match(check_string)
                if match != None:
                    key_found = regexp[0]
                    break
            else:
                o += s[i]
                i += 1
                continue
            start, end = match.span()
            if key_found == 'href':
                href_content = check_string[start+2:end-1]
                delimiter = href_content.find(':')
                link_key = href_content[:delimiter]
                link_value = href_content[delimiter + 1:]
                self.links[link_key] = link_value
                i += (end - 1) if i == 0 else (end)
            else:
                rstart = 0 if i == 0 else len(o) + 1
                a[key_found].append([rstart, rstart + (end - start) - 5])
                o += check_string[start] + check_string[start+2:end-2]
                i += end - 1
        return a, o

    def get_title(self, s):
        ''' Return the title level if the text is a title '''
        subs = [{'char': '-', 'level': 2}, {'char': '=', 'level': 1}]
        l = len(s)  # Must be non even
        for sub in subs:
            if s[(l/2):] == ' ' + sub['char'] * (l/2):
                return sub['level'], s[:(l/2)]
        return 0, None

# wrap lines in <span>s so that the Moin-generated line numbers work
class NomarkHtmlFormatter(HtmlFormatter):
    pass
    def wrap(self, source, outfile):
        for i, t in source:
            yield i, t
            # 1, '<span class="line">' + line[1] + '</span>'

class Render:
    def __init__(self):
        self.inlist = False

    def header(self, title):
        o = '<!DOCTYPE html>\n<html lang="en">\n'
        o += '<head>\n<meta charset=utf-8>\n<title>{}</title>\n'.format(title)
        o += '<meta name="viewport" content="width=device-width,'
        o += 'initial-scale=1.0">\n'
        o += '<link rel="stylesheet" type="text/css" '
        o += 'href="dist/css/bootstrap.css" media="screen">\n'
        o += '<link rel="stylesheet" type="text/css" '
        o += 'href="dist/css/bootstrap-theme.css" media="screen">\n'
        o += '<link rel="stylesheet" type="text/css" '
        o += 'href="syntax.css" media="screen">\n'
        o += '</head>\n'
        o += '<body>\n'
        o += '<div class="container">\n'
        return o

    def footer(self):
        o = '</div>'
        o += '</body>\n</html>\n'
        return o

    def render(self, parser):
        o = self.header('patatas')
        writers = { 'title': self.render_title,
                    'regular': self.render_regular,
                    'code': self.render_code,
                    'list': self.render_list}
        for para in parser.pars:
            # Adjustement for lists concatenation
            if self.inlist == True and para['type'] != 'list':
                o += '</ul>\n'
                self.inlist = False
            # Paragraph format
            o += writers[para['type']](para, parser.links)
        o += self.footer()
        return o

    def render_title(self, para, links):
        return '<h{level}>{text}</h{level}>'.format(level=para['level'],
                                                    text=para['text'])
    def render_regular(self, para, links):
        o = '<p>'
        o += self.render_para(para, links)
        o += '</p>\n'
        return o

    def render_list(self, para, links):
        o = ''
        if self.inlist == False:
            o = '<ul>\n'
            self.inlist = True
        o += '  <li>'
        o += self.render_para(para, links)
        o += '</li>\n'
        return o

    def render_para(self, para, links):
        o = ''
        attribs = [
            {'key': 'bold', 'start': '<b>', 'end': '</b>'},
            {'key': 'underline', 'start': '<em>', 'end': '</em>'},
            {'key': 'code', 'start': '<code>', 'end': '</code>'},
            {'key': 'link', 'start': '<a href="{}">', 'end': '</a>'}]
        for i in xrange(len(para['text'])):
            append = ''
            for attrib in attribs:
                key = attrib['key']
                for start, end in para[attrib['key']]:
                    if i == start:
                        if key == 'link':
                            href = links[para['text'][start:end+1]]
                            o += attrib['start'].format(href)
                        else:
                            o += attrib['start']
                    elif i == end:
                        append += attrib['end']
            o += escape(para['text'][i], True) + append
        return o

    def render_table(self, string):
        r = '<table class="table">'
        for index, row in enumerate(csv.reader(StringIO(string))):
            r += '<tr>'
            for cell in row:
                tag = 'th' if index == 0 else 'td'
                r += '<{}>{}</{}>'.format(tag, cell, tag)
            r += '</tr>'
            # r += str(row)
        r +='</table>'
        return r

    def render_a2s(self, string):
        p = Popen(['php', '/usr/share/asciitosvg/a2s'],
                  stdout=PIPE, stdin=PIPE)
                    # , stderr=STDOUT)
        # r = '<svg width="237px" height="45px" version="1.1">'
        r = sjoin(p.communicate(input=string)[0].split('\n')[4:], '\n')
        return r

    def render_code(self, para, links):
        self.inlist = False
        if para['lang'] == 'table':
            return self.render_table(para['text'])
        elif para['lang'] == 'a2s':
            return self.render_a2s(para['text'])
        try:
            lexer = get_lexer_by_name(para['lang'])
        except ClassNotFound:
            lexer = TextLexer()
        htmlformatter = NomarkHtmlFormatter(linenos=False)
        result = highlight(para['text'], lexer, htmlformatter)
        #return '<pre>\n{text}</pre>\n'.format(text=escape(para['text'], True))
        return '<pre class="syntax">\n{text}</pre>\n'.format(text=result)

nomark = Parser(sys.argv[1])
html5 = Render()
# print json.dumps(nomark.pars, indent=2)
print(html5.render(nomark))
