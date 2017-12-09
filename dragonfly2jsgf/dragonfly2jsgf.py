import logging

import jsgf
from dragonfly import Grammar
from dragonfly.grammar.elements import *
from dragonfly.grammar.elements_compound import stuff
from dragonfly.grammar.rule_base import Rule
from dragonfly.parser import Parser, ParserError
from jsgf.ext import SequenceRule


class TranslationError(Exception):
    pass


class JSGFImpossible(jsgf.Expansion):
    """
    JSGF equivalent of dragonfly's Impossible element.
    """
    def __init__(self):
        super(JSGFImpossible, self).__init__([])

    def matches(self, speech):
        self.current_match = None
        return speech


class LinkedGrammar(jsgf.Grammar):
    def __init__(self, name, df_grammar):
        self._df_grammar = df_grammar
        super(LinkedGrammar, self).__init__(name=name)

    @property
    def df_grammar(self):
        """
        Dragonfly grammar that this one was built from.
        :return: Grammar
        """
        return self._df_grammar


class LinkedRule(jsgf.Rule):
    def __init__(self, name, visible, expansion, df_rule):
        self._df_rule = df_rule
        super(LinkedRule, self).__init__(name, visible, expansion)

    @property
    def df_rule(self):
        """
        Dragonfly rule that this one was built from.
        :return: Rule
        """
        return self._df_rule


class TranslationState(object):
    """
    Translation state used in building a JSGF expansion tree
    from a dragonfly rule
    """
    def __init__(self, element, expansion=None, dependencies=None):
        """
        :type element: ElementBase
        """
        self.element = element
        self._expansion = expansion
        if isinstance(dependencies, list):
            self.dependencies = dependencies
        else:
            self.dependencies = []

    rule_names = property(
        lambda self: map(lambda rule: rule.name, self.dependencies)
    )

    @property
    def expansion(self):
        return self._expansion

    @expansion.setter
    def expansion(self, value):
        # Valid values are an Expansion object or None
        if value is not None and not isinstance(value, jsgf.Expansion):
            raise AttributeError("value must be an Expansion object or None.")

        self._expansion = value


class Translator(object):
    _log = logging.getLogger("dragonfly2jsgf")
    _parser = Parser(stuff, _log)

    def translate(self, df_spec):
        element = self._parser.parse(df_spec)
        if not element:
            raise ParserError("Invalid dragonfly spec: %r" % df_spec)

        assert isinstance(element, ElementBase)
        state = TranslationState(element)
        return self.get_jsgf_equiv(state)

    def translate_grammar(self, grammar):
        """
        Translate a dragonfly grammar into a JSGF grammar.
        :type grammar: Grammar
        :rtype: LinkedGrammar
        """
        result = LinkedGrammar(grammar.name, grammar)
        for rule in grammar.rules:
            result.add_rule(self.translate_rule(rule))
        return result

    def translate_rule(self, rule, visible=True):
        """
        Translates a dragonfly rule into a JSGF rule.
        :type rule: Rule
        :type visible: bool
        :rtype: LinkedRule
        """
        element = rule.element
        state = self.get_jsgf_equiv(TranslationState(element))
        jsgf_rule = LinkedRule(rule.name, visible, state.expansion, rule)
        return jsgf_rule

    def translate_rule_ref(self, state):
        """
        Translate the dragonfly RuleRef object inside the TranslationState
        object by collecting all of the rules as necessary using the
        'dependencies' list.
        :type state: TranslationState
        :return TranslationState
        """
        element = state.element
        if not isinstance(element, RuleRef):
            raise TranslationError("Cannot translate element '%s' as a "
                                   "RuleRef." % state.element)
        name = element.name
        if name not in state.rule_names:
            # Make a new equivalent JSGF rule
            rule_expansion = self.get_jsgf_equiv(element.rule.element)
            new_rule = jsgf.Rule(name, False, rule_expansion)
            state.dependencies.append(new_rule)
            state.expansion = jsgf.RuleRef(new_rule)
        else:
            # Use the existing rule
            index = state.rule_names.index(name)
            state.expansion = jsgf.RuleRef(state.dependencies[index])

        return state

    def translate_to_rule(self, rule_name, df_spec, visible=True):
        expansion = self.translate(df_spec).expansion
        return jsgf.Rule(rule_name, visible, expansion)

    def get_jsgf_equiv(self, state):
        """
        Take a TranslationState object containing a dragonfly element
        return the same object with the 'expansion' member set to the
        equivalent JSGF expansion object.
        :type state: TranslationState
        :return TranslationState
        """
        element = state.element

        def get_equiv_children():
            children = []
            for child in state.element.children:
                state.element = child
                self.get_jsgf_equiv(state)
                children.append(state.expansion)
            return children

        if isinstance(element, Literal):  # Literal == word list
            state.expansion = jsgf.Literal(element.gstring())

        elif isinstance(element, (RuleRef, Rule)):
            # Translate the dragonfly rule reference
            self.translate_rule_ref(state)

        elif isinstance(element, (ListRef, List, DictListRef, DictList)):
            raise NotImplementedError("Dragonfly Lists and DictLists are "
                                      "not implemented yet.")

        elif isinstance(element, Dictation):
            # A Sphinx decoder for handling dictation will be prepared and used
            # when necessary.
            state.expansion = jsgf.ext.Dictation()

        elif isinstance(element, Impossible):
            state.expansion = JSGFImpossible()

        elif element.children == ():  # improbable ElementBase case
            state.expansion = jsgf.Expansion([])

        elif isinstance(element, Sequence):
            state.expansion = jsgf.Sequence(*get_equiv_children())

        elif isinstance(element, Alternative):
            if len(state.element.children) == 1:
                # Skip redundant (1 child) alternatives
                state.element = state.element.children[0]
                self.get_jsgf_equiv(state)
            else:
                state.expansion = jsgf.AlternativeSet(*get_equiv_children())

        elif isinstance(element, Optional):
            equiv_children = get_equiv_children()
            if len(equiv_children) != 1:
                raise TranslationError("Optional grouping may only have 1 child.")
            state.expansion = jsgf.OptionalGrouping(equiv_children[0])

        elif isinstance(element, Repetition):
            equiv_children = get_equiv_children()
            if len(equiv_children) != 1:
                raise TranslationError("Repetition may only have 1 child.")
            state.expansion = jsgf.Repeat(equiv_children[0])

        return state
