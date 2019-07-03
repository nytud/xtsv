import sys
from argparse import ArgumentParser, FileType, REMAINDER


def add_bool_arg(parser, name, help_text, default=False, has_negative_variant=True):
    # Original version of the code is code from:
    #  https://stackoverflow.com/questions/15008758/parsing-boolean-values-with-argparse/31347222#31347222
    group = parser  # the main parser is the default
    if has_negative_variant:  # Add exclusive group only when there is negative variant!
        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument('--no-' + name, dest=name.replace('-', '_'), help='{0} (negative variant)'.format(help_text),
                           action='store_false')

    # Add positive variant to the main parser or to the group as needed
    group.add_argument('--' + name, dest=name.replace('-', '_'), help=help_text, action='store_true')
    parser.set_defaults(**{name: default})


def parser_skeleton(*args, **kwargs):
    parser = ArgumentParser(*args, **kwargs)
    # Argparse magic: https://docs.python.org/dev/library/argparse.html#nargs
    parser.add_argument('-i', '--input', dest='input_stream', type=FileType(), default=sys.stdin,
                        help='Use input file instead of STDIN (only allowed when at least one task is specified!)',
                        metavar='FILE')
    parser.add_argument('-o', '--output', dest='output_stream',  type=FileType('w'), default=sys.stdout,
                        help='Use output file instead of STDOUT (only allowed when at least one task is specified!)',
                        metavar='FILE')

    add_bool_arg(parser, 'verbose', 'Show warnings')
    add_bool_arg(parser, 'conllu-comments', 'Enable CoNLL-U style comments')

    parser.add_argument(dest='task', nargs=REMAINDER)

    return parser
