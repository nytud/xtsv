#!/usr/bin/env python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import importlib
import codecs
from itertools import chain
from collections import defaultdict, OrderedDict, abc

# import atexit

from json import dumps as json_dumps

from flask import Flask, request, Response, stream_with_context, make_response
from flask_restful import Api, Resource
from werkzeug.exceptions import abort

from .tsvhandler import process, HeaderError
from .jnius_wrapper import jnius_config, import_pyjnius


class ModuleError(ValueError):
    pass


def build_pipeline(input_data, used_tools, available_tools, presets, conll_comments=False, singleton_store=None,
                   output_header=True):
    friendly_name_for_modules = {name: tool_params[1] for tool_params, names in available_tools for name in names}
    current_initialised_tools = lazy_init_tools(used_tools, available_tools, presets, singleton_store)

    used_tools = resolve_presets(presets, used_tools)

    if isinstance(input_data, str):
        inp_stream = iter(input_data.splitlines(keepends=True))
    elif isinstance(input_data, abc.Iterable):
        inp_stream = input_data
    else:
        raise ValueError('The input should be string or iterable!')

    # Peek header...
    header = next(inp_stream)
    # ...and restore iterator...
    inp_stream = chain([header], inp_stream)

    pipeline_begin = inp_stream
    pipeline_begin_friendly = 'Input Text'
    pipeline_begin_prod = set(header.strip().split('\t'))

    pipeline_end = pipeline_begin
    pipeline_end_friendly = pipeline_begin_friendly
    pipeline_prod = pipeline_begin_prod

    last_used_tool_nr = len(used_tools) - 1
    for i, program in enumerate(used_tools):
        program_friendly = friendly_name_for_modules[program]
        pr = current_initialised_tools.get(program)
        if pr is not None:
            if i == 0 and len(pr.source_fields) == 0:  # If first module expects raw text, there are no fields!
                pipeline_prod = set()
            if not pr.source_fields.issubset(pipeline_prod):
                raise ModuleError('ERROR: \'{0}\' module requires {1} fields but the previous module \'{2}\''
                                  ' has only {3} fields!'.format(program_friendly, pr.source_fields,
                                                                 pipeline_end_friendly, pipeline_prod))
            pipeline_end = process(pipeline_end, pr, conll_comments, i != last_used_tool_nr or output_header)
            pipeline_end_friendly = program_friendly
            pipeline_prod |= set(pr.target_fields)
        else:
            raise ModuleError('ERROR: \'{0}\' module not found. Available modules: {1}'.
                              format(program, ','.join(m for _, names in available_tools for m in names)))

    return pipeline_end


def pipeline_rest_api(name, available_tools, presets, conll_comments, singleton_store=None, form_title='xtsv pipeline',
                      form_type='checkbox', doc_link='', output_header=True):
    if available_tools is None:
        raise ValueError('No internal_app is given!')

    kwargs = {'internal_apps': available_tools, 'presets': presets, 'conll_comments': conll_comments,
              'singleton_store': singleton_store, 'form_title': form_title, 'form_type': form_type,
              'doc_link': doc_link, 'output_header': output_header}

    app = Flask(name)
    api = Api(app)
    api.add_resource(RESTapp, '/', '/<path:path>', resource_class_kwargs=kwargs)  # Catch-all with self

    return app


def singleton_store_factory():
    """ Store already initialised tools for reuse without reinitialization (singleton store)
         must explicitly pass it to init_everything() or pipeline_rest_api()
    """
    return {}, defaultdict(list)


# From here, there are only private methods
def resolve_presets(presets, used_tools):  # Resolve presets to module names to enable shorter URLs/task definitions...
    if len(used_tools) == 1 and used_tools[0] in presets:
        used_tools = presets[used_tools[0]][1]
    return used_tools


def lazy_init_tools(used_tools, available_tools, presets, singleton_store=None):
    """ Resolve presets and initialise what is needed if it were not initialised before or not available """
    # Sanity check params!
    for app, _ in available_tools:
        if not isinstance(app, tuple):
            raise TypeError('When using lazy initialisation internal_apps should be'
                            ' the dict of the uninitialised tools!')
        module, prog, friendly_name, prog_args, prog_kwargs = app
        try:
            importlib.import_module(module), prog   # Silently import everything for the JAVA CLASSPATH...
        except ModuleNotFoundError:
            pass

    # Resolve presets to module names to init only the needed modules...
    used_tools = set(resolve_presets(presets, used_tools))

    # If there is preinitialised tool pool check the type, else create a new!
    if singleton_store is None:
        singleton_store = singleton_store_factory()
    elif not isinstance(singleton_store, tuple) or len(singleton_store) != 2 or \
            not isinstance(singleton_store[0], dict) or not isinstance(singleton_store[1], defaultdict) or \
            not issubclass(singleton_store[1].default_factory, list):
        raise ValueError('singleton_store  is expected to be the type of tuple(dict(), defaultdict(list))'
                         ' instead of {0} !'.format(type(singleton_store)))

    selected_tools = [(k, v) for k, v in available_tools if len(used_tools.intersection(set(v)))]
    # Init everything properly
    # Here we must challenge if any classpath or JAVA VM options are set to be able to throw the exception if needed
    if jnius_config.classpath is not None or len(jnius_config.options) > 0:
        import_pyjnius()

    current_initialised_tools = singleton_store[0]
    currrent_alias_store = singleton_store[1]
    for prog_params, prog_names in selected_tools:  # prog_names are individual, prog_params can be the same!
        module, prog, friendly_name, prog_args, prog_kwargs = prog_params
        # Dealias aliases to find the initialised versions
        for inited_prog_names, curr_prog_params in currrent_alias_store[prog]:
            if curr_prog_params == prog_params:  # If prog_params match prog_name is an alias for inited_prog_names
                for prog_name in prog_names:
                    current_initialised_tools[prog_name] = current_initialised_tools[inited_prog_names[0]]
                break
        else:  # No initialised alias found... Initialize and store as initialised alias!
            prog_imp = getattr(importlib.import_module(module), prog)
            inited_prog = prog_imp(*prog_args, **prog_kwargs)  # Inint programs...
            if (not hasattr(inited_prog, 'source_fields') or not isinstance(inited_prog.source_fields, set)) and \
               (not hasattr(inited_prog, 'target_fields') or not isinstance(inited_prog.target_fields, list)):
                raise ModuleError('Module named {0} has no source_fields or target_fields attributes'
                                  ' or some of them has wrong type !'.format(','.join(prog_names)))
            for prog_name in prog_names:
                current_initialised_tools[prog_name] = inited_prog
            currrent_alias_store[prog].append((prog_names, prog_params))  # For lookup we need prog_names as well!
    return current_initialised_tools


class RESTapp(Resource):
    _html_style = """<style>
                body, html {
                    width: 100%;
                    height: 100%;
                    margin: 0;
                    padding: 10px;
                    display:table;
                }
                body {
                    display:table-cell;
                    vertical-align:middle;
                }
                div {
                    white-space: nowrap; /*Prevents Wrapping*/

                    overflow-x: hidden;
                    overflow-y: hidden;
                }
            </style>"""

    # str.replace() is used instead of str.format() because the many curly brackets!
    _html_on_submit_form = """function OnSubmitForm() {
                    var text = document.mainForm.inputText.value;

                    if (text.length == 0 && (document.getElementsByName('inputfile').length == 0 ||
                        document.mainForm.inputfile.files.length == 0)) {
                        alert('Input is empty!');
                        return false;
                    }

                    var url = 'BASE_URL_PLACEHOLDER';

                    var none_are_checked = true;
                    // Get all the checkboxes in order...
                    var fields = document.mainForm.tools.getElementsByTagName('input');
                    for(var i = 0; i < fields.length; ++i) {
                        if(fields[i].checked) {
                            // ...and append checked ones to the URL to get the proper tool list!
                            url += '/' + fields[i].value;
                            none_are_checked = false;
                        }
                    }

                    if (none_are_checked) {
                        alert('At least one tool must be selected!');
                        return false;
                    }

                    document.mainForm.submit.disabled = true;  // Prevent double submit!

                    if (fields[0].type != 'radio') {
                        var data = new FormData();

                        if (document.mainForm.inputfile.files.length > 0) {
                            var file = document.mainForm.inputfile.files[0]
                            data.append('file', file, file.name);
                        }
                        else {
                            var blob = new Blob([text], {type:'text/plain'});
                            data.append('file', blob, 'input.txt');
                        }
                        if (document.mainForm.outputMode.value == 'display') {
                            data.append('toHTML', true);
                        }
                    }
                    else {
                        url += '/' + text;
                    }

                    function initDownload(blob) {
                        var link = document.createElement('a');  // Initiate download
                        link.href = window.URL.createObjectURL(blob);
                        link.download = 'output.txt';
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                    }

                    function writeError(msg) {
                        var div = document.createElement('div');
                        div.innerHTML = msg.trim();
                        var text =  div.getElementsByTagName('p')[0].innerHTML;
                        document.getElementById('result').innerHTML = text;
                    }

                    function pprint(text) {
                        if (fields[0].type != 'radio') {
                            return text;
                        }
                        else {
                            return '<pre>' + text + '</pre>';
                        }
                    }

                    var fetchHandle = function(response) {
                        if (response.ok) {
                            if (document.mainForm.outputMode.value == 'display') {  // ...write result!
                                response.text().then(text =>
                                                     document.getElementById('result').innerHTML = pprint(text));
                            }
                            else {
                                document.getElementById('result').innerHTML = '';  // Purge possible previous result 
                                response.blob().then(resp => initDownload(resp));
                            }
                        }
                        else {
                            response.text().then(writeError);
                        }
            
                        document.mainForm.submit.disabled = false;  // Reenable submit!
                    };
                    if (fields[0].type != 'radio') {
                        var params = {method: 'POST', credentials: 'include', body: data};
                    }
                    else {
                        var params = {method: 'GET', credentials: 'include'};
                    }
                    fetch(url, params).then(fetchHandle).catch(fetchHandle);
                    return false; // Do not submit actually, as fetch has already done it...
                }
                function OnChangeFile() {
                    if (document.mainForm.inputfile.files.length > 0) {
                        document.mainForm.inputText.value = '';
                    }
                }
                function OnChangeTextarea() {
                    if (document.mainForm.inputText.value.length > 0) {
                        document.mainForm.inputfile.value = document.mainForm.inputfile.defaultValue;
                    }
                }"""

    # str.replace() is used instead of str.format() because the many curly brackets!
    _html_w_presets = """function OnChangePreset() {
                    var val = document.mainForm.presets.value;

                    if (val == '') {
                        return true;  // If None is selected, do nothing...
                    }

                    var preset2tools = {};

                    PRESETS_PLACEHOLDER

                    var currTools = preset2tools[val];

                    // Get all the checkboxes in order...
                    var fields = document.mainForm.tools.getElementsByTagName('input');
                    for(var i = 0; i < fields.length; ++i) {
                        // ...and set appropriate checked states.
                        fields[i].checked = currTools.has(fields[i].value);
                    }
                }

                function OnChangeCheckbBox() {
                    document.mainForm.presets.value = '';
                }"""

    # str.format() is used to replace the dynamic parts
    _presets_js_template = '                    preset2tools[\'{0}\'] = new Set({1});'

    # str.format() is used to replace the dynamic parts
    _presets_html_template = '                       <option value="{0}">{1}</option>'

    _html_wo_presets = """function OnChangeCheckbBox() {
                }"""

    # str.format() is used to replace the dynamic parts
    _html_w_presets2 = """<p>
                   <label for="presets">Available presets:</label><br/>
                   <select name="presets" id="presets" onchange="OnChangePreset()">
                       <option value="">None</option>
                       {0}
                   </select>
               </p>"""

    # str.format() is used to replace the dynamic parts
    _html_main = """<!DOCTYPE html>
    <html lang="en-US">

        <head>
            <meta charset="UTF-8">
            <title>{0}</title>
            {1}
            <script>
                {2}
                {3}
            </script>
        </head>
        <body>
            <form name="mainForm" method="POST" onsubmit="return OnSubmitForm();" id="mainForm">
               {4}
               <p>
                   <label for="tools">
                   Available tools (see <a href="{5}">documentation</a> for more details on usage):</label><br/>
                   <fieldset name="tools" id="tools" style="border: 0;">
                       {6}
                   </fieldset>
               </p>
               <p>
                   {7}
               </p>
               {9}
               <input type="submit" name="submit" value="Process"><br/>
            </form>
        <p>Result: </p>
        <div id="result" name="result"></div>
        </body>
    </html>
    """

    _text_or_file = """<label for="inputText">Input text or file:</label><br/><br/>
                   <input type="file" id="inputfile" name="inputfile" onchange="OnChangeFile()" /><br/><br/>
                   <textarea autofocus rows="10" cols="80" placeholder="Enter text here..." form="mainForm"
                    name="inputText" id="inputText" {8}></textarea><br/>"""
    _text_or_file_radio = """<label for="inputText">Input word:</label><br/><br/>
                       <input type="text" name="inputText" id="inputText" placeholder="Enter word here..." />"""

    _text_or_file2 = 'onchange="OnChangeTextarea()"'
    _text_or_file3 = """<p>
                   <label for="outputMode">Output mode:</label><br/>
                   <select name="outputMode" id="outputMode">
                       <option value="display">Display below</option>
                       <option value="download">Download</option>
                   </select><br/>
               </p>"""

    # Replace: 'checkbox'|'radio', tool_name, friendly_name
    _html_tool = '                       <input type="{0}" {3}name="availableTools" id="{1}" value="{1}"/>' \
                 '<label for="{1}">{2}</label><br/>'

    def gen_html_form(self, base_url):
        if len(self._presets) > 0:
            presets_js_cont = '\n'.join(self._presets_js_template.format(preset_name, str(tools_list[1]))
                                        for preset_name, tools_list in self._presets.items()).lstrip()
            presets_js_formatted = self._html_w_presets.replace('PRESETS_PLACEHOLDER', presets_js_cont)

            presets_html_cont = '\n'.join(self._presets_html_template.format(preset_name, friendly_name)
                                          for preset_name, (friendly_name, tools_list)
                                          in self._presets.items()).lstrip()
            presets_html_formatted = self._html_w_presets2.format(presets_html_cont)
        else:
            presets_js_formatted = self._html_wo_presets
            presets_html_formatted = ''
        if self._tools_type == 'radio':
            text_or_file = self._text_or_file_radio
            text_or_file2 = ''
            text_or_file3 = '<input type="hidden" name="outputMode" id="outputMode" value="display">'
            on_change = ''
        else:
            text_or_file = self._text_or_file
            text_or_file2 = self._text_or_file2
            text_or_file3 = self._text_or_file3
            on_change = 'onchange="OnChangeCheckbBox()" '
        html_tools = '\n'.join(self._html_tool.format(self._tools_type, tool_name, friendly_name, on_change)
                               for tool_name, friendly_name in self._available_tools.items()).lstrip()
        out_html = self._html_main.format(self._title, self._html_style,
                                          self._html_on_submit_form.replace('BASE_URL_PLACEHOLDER', base_url),
                                          presets_js_formatted, presets_html_formatted, self._doc_link, html_tools,
                                          text_or_file, text_or_file2, text_or_file3)
        return out_html

    def __init__(self, internal_apps=None, presets=(), conll_comments=False, singleton_store=None,
                 form_title='xtsv pipeline', form_type='checkbox', doc_link='', output_header=True):
        """
        Init REST API class
        :param internal_apps: pre-inicialised applications
        :param presets: pre-defined chains eg. from tokenisation to dependency parsing'
        :param conll_comments: CoNLL-U-style comments (lines beginning with '# ') before sentences
        :param singleton_store: preinitialised tool pool, which mustbe defined externally,
                or new is created on every call!
        :param form_title: the title of the HTML form shown when URL opened in a browser
        :param form_type: Some tools can be used as alternatives (e.g. different modes of emMorph),
                some allow sequences to be defined
        :param doc_link: A link to documentation on usage for helping newbies
        :param output_header: Make header for output or not
        """
        self._internal_apps = internal_apps
        self._presets = presets
        self._conll_comments = conll_comments
        self._output_header = output_header

        self._singleton_store = singleton_store
        self._title = form_title
        if form_type not in {'checkbox', 'radio'}:
            raise ValueError('form_type should be either \'checkbox\' or \'radio\' instead of {0}'.format(form_type))
        if form_type == 'radio' and len(presets) != 0:
            raise ValueError('Presets and radio buttons are mutually exclusive options!')
        self._tools_type = form_type

        self._doc_link = doc_link

        # Dict of default tool names -> friendly names # TODO: OrderedDict is not necessary for >= Python 3.7!
        self._available_tools = OrderedDict((names[0], tool_params[2]) for tool_params, names in internal_apps)
        # atexit.register(self._internal_apps.__del__)  # For clean exit...

    def get(self, path=''):
        # fun/token
        fun, token = None, ''
        if '/' in path:
            fun, token = path.split('/', maxsplit=1)
        curr_tools = lazy_init_tools([fun], self._internal_apps, self._presets, self._singleton_store)
        prog = getattr(curr_tools.get(fun), 'process_token', None)

        if len(path) == 0 or len(token) == 0 or prog is None:
            base_url = request.url_root.rstrip('/')  # FORM URL

            out_html = self.gen_html_form(base_url)
            return Response(out_html)

        json_text = json_dumps({token: prog(token)}, indent=2, sort_keys=True, ensure_ascii=False)

        return self._make_json_response(json_text)

    def post(self, path):
        tohtml = request.form.get('toHTML', False)
        if tohtml:
            final_convert = self._to_html
        else:
            final_convert = self._identity

        conll_comments = self._get_checked_bool('conll_comments', self._conll_comments)
        output_header = self._get_checked_bool('output_header', self._output_header)
        input_text = request.form.get('text')
        if 'file' in request.files and input_text is None:
            inp_data = codecs.getreader('UTF-8')(request.files['file'])
        elif 'file' not in request.files and input_text is not None:
            inp_data = input_text
        else:
            abort(400, 'ERROR: input text or file (mutually exclusive) not found in request!')
            inp_data = None  # Silence dummy IDE

        required_tools = path.split('/')

        try:
            last_prog = build_pipeline(inp_data, required_tools, self._internal_apps, self._presets, conll_comments,
                                       self._singleton_store, output_header)
        except (HeaderError, ModuleError) as e:
            abort(400, e)
            last_prog = ()  # Silence, dummy IDE

        response = Response(stream_with_context(final_convert((line.encode('UTF-8') for line in last_prog))),
                            direct_passthrough=True, content_type='text/plain; charset=utf-8')
        if not tohtml:
            response.headers.set('Content-Disposition', 'attachment', filename='output.txt')
        return response

    @staticmethod
    def _get_checked_bool(input_param_name, default):
        input_param = request.form.get(input_param_name, default)
        if not isinstance(input_param, bool):
            if input_param.lower() == 'true':
                input_param = True
            elif input_param.lower() == 'false':
                input_param = False
            else:
                abort(400, 'ERROR: argument {0} should be True/False!'.format(input_param_name))
        return input_param

    @staticmethod
    def _make_json_response(json_text, status=200):
        """
         https://stackoverflow.com/questions/16908943/display-json-returned-from-flask-in-a-neat-way/23320628#23320628
        """
        response = make_response(json_text)
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['mimetype'] = 'application/json'
        response.status_code = status
        return response

    @staticmethod
    def _identity(x):
        return x

    @staticmethod
    def _to_html(input_iterator):
        for line in input_iterator:
            yield line.rstrip(b'\n').replace(b'&', b'&amp;').replace(b'<', b'&lt;').replace(b'>', b'&gt;').\
                replace(b'"', b'&quot;').replace(b'\'', b'&#x27;')
            yield b'<br/>\n'
