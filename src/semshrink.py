class LimitFuzzer:
    def tree_to_str(self, tree):
        name, children = tree
        if not children: return name
        return ''.join(self.tree_to_str(c) for c in children)

    def select(self, lst):
        return random.choice(lst)

    def symbol_cost(self, grammar, symbol, seen):
        if symbol in self.key_cost: return self.key_cost[symbol]
        if symbol in seen:
            self.key_cost[symbol] = float('inf')
            return float('inf')
        v = min((self.expansion_cost(grammar, rule, seen | {symbol})
                    for rule in grammar.get(symbol, [])), default=0)
        self.key_cost[symbol] = v
        return v

    def expansion_cost(self, grammar, tokens, seen):
        return max((self.symbol_cost(grammar, token, seen)
                    for token in tokens if token in grammar), default=0) + 1

    def gen_key(self, key, depth, max_depth):
        if key not in self.grammar: return (key, [])
        if depth > max_depth:
            clst = sorted([(self.cost[key][str(rule)], rule) for rule in self.grammar[key]])
            rules = [r for c,r in clst if c == clst[0][0]]
        else:
            rules = self.grammar[key]
        return (key, self.gen_rule(self.select(rules), depth+1, max_depth))

    def gen_rule(self, rule, depth, max_depth):
        return [self.gen_key(token, depth, max_depth) for token in rule]

    def fuzz(self, key='<start>', max_depth=10):
        return self.tree_to_str(self.gen_key(key=key, depth=0, max_depth=max_depth))

    def __init__(self, grammar):
        self.grammar = grammar
        self.key_cost = {}
        self.cost = self.compute_cost(grammar)

    def compute_cost(self, grammar):
        cost = {}
        for k in grammar:
            cost[k] = {}
            for rule in grammar[k]:
                cost[k][str(rule)] = self.expansion_cost(grammar, rule, set())
        return cost


class ComplexFuzzer(LimitFuzzer):
    def __init__(self, grammar):
        def cfg(g):
            return {k: [self.cfg_rule(r) for r in g[k]] for k in g}
        super().__init__(cfg(grammar))
        self.cfg_grammar = self.grammar
        self.grammar = grammar
        self.vars = []
        self._vars = []

    def cfg_rule(self, rule):
        return [t[0] if isinstance(t, tuple) else t for t in rule]

    def gen_key(self, key, depth, max_depth):
        if key not in self.grammar: return (key, [])
        if depth > max_depth:
            clst_ = [(self.cost[key][str(self.cfg_rule(rule))], rule) for rule in self.grammar[key]]
            clst = sorted(clst_, key=lambda x: x[0])
            rules = [r for c,r in clst if c == clst[0][0]]
        else:
            rules = self.grammar[key]
        return (key, self.gen_rule(self.select(rules), depth+1, max_depth))

    def gen_rule(self, rule, depth, max_depth):
        ret = []
        for token_ in rule:
            if isinstance(token_, tuple):
                token = token_[0]
                fns = token_[1]
            else:
                token = token_
                fns = {}

            pre = fns.get('pre', lambda s, t, x: x())
            post = fns.get('post', lambda s, x: x)
            val = pre(self, token, lambda: self.gen_key(token, depth, max_depth))
            v = post(self, val)
            ret.append(v)
        return ret

def defining_var(o, val):
    v = o.tree_to_str(val)
    o._vars.append(v)
    return val

def defined_var(o, token, val):
    assert token == '<var>'
    #v = val()
    if not o.vars:
        return ('00', [])
    else:
        return (o.select(o.vars), [])

def sync(o, val):
    o.vars.extend(o._vars)
    o._vars.clear()
    return val

class ChoiceFuzzer(ComplexFuzzer):
    def __init__(self, grammar, choices):
        super().__init__(grammar)
        self.choices = choices

    def select(self, lst):
        return self.choices.choice(lst)


class ChoiceSeq:
    def __init__(self, ints=None):
        self.index = -1
        if ints is None:
            self.ints = []
            self.choose_new = True
        else:
            self.ints = ints
            self.choose_new = False

    def i(self):
        if self.choose_new:
            self.index += 1
            self.ints.append(random.randrange(10))
            return self.ints[self.index]
        else:
            self.index += 1
            return self.ints[self.index]

    def choice(self, lst):
        return lst[self.i() % len(lst)]

def remove_check_each_fragment(instr, start, part_len, causal):
    for i in range(start, len(instr), part_len):
        stitched =  instr[:i] + instr[i+part_len:]
        if causal(stitched): return i, stitched
    return -1, instr

def ddmin(cur_str, causal_fn):
    start, part_len = 0, len(cur_str) // 2
    while part_len >= 1:
        start, cur_str = remove_check_each_fragment(cur_str, start, part_len, causal_fn)
        if start != -1:
            if not cur_str: return ''
        else:
            start, part_len = 0, part_len // 2
    return cur_str

def pred(v):
    if v is None: return False

    if '((' in v and '))' in v:
        return True
    return False

def ints_to_string(grammar, ints):
    choices = ChoiceSeq(ints)
    cf = ChoiceFuzzer(grammar, choices)
    try:
        return cf.fuzz('<start>')
    except IndexError:
        return None

if __name__ == '__main__':
    import random
    import string
    import sys
    random.seed(int(sys.argv[1]))
    assignment_grammar = {
            '<start>' : [[ '<assignments>' ]],
            '<assignments>': [['<assign>', (';\n', {'post':sync})], ['<assign>', (';\n', {'post':sync}), '<assignments>']],
            '<assign>': [[('<var>', {'post':defining_var}), ' = ', '<expr>']],
            '<expr>': [
                ['<expr>', ' + ', '<expr>'],
                ['<expr>', ' - ', '<expr>'],
                ['(', '<expr>', ')'],
                [('<var>', {'pre':defined_var})],
                ['<digit>']],
            '<digit>': [['0'], ['1']],
            '<var>': [[i] for i in string.ascii_lowercase]
    }
    choices = ChoiceSeq()

    c = ChoiceFuzzer(assignment_grammar, choices)
    val = c.fuzz('<start>')

    causal_fn = lambda ints: pred(ints_to_string(assignment_grammar, ints))

    if pred(val):
        newv = ddmin(c.choices.ints, causal_fn)
        choices = ChoiceSeq(newv)
        cf = ChoiceFuzzer(assignment_grammar, choices)
        print('original:', val, len(c.choices.ints))

        while True:
            newv = ddmin(cf.choices.ints, causal_fn)
            if len(newv) >= len(cf.choices.ints):
                break
            cf = ChoiceFuzzer(assignment_grammar, ChoiceSeq(newv))

        cf = ChoiceFuzzer(assignment_grammar, ChoiceSeq(newv))
        print('minimal:', cf.fuzz('<start>'), len(newv))
        print(cf.choices.ints)

