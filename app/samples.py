SAMPLE_REFERENCE = "a, b = map(int, input().split())\nprint(a + b)\n"
SAMPLE_GENERATOR = '''import random, sys
seed = int(sys.stdin.readline())
LIM = 10**9
if seed == 1:
    a, b = -LIM, -LIM          # minimum
elif seed == 2:
    a, b = LIM, LIM            # maximum
elif seed == 3:
    a, b = 0, 0                # edge
else:
    r = random.Random(seed)
    k = r.choice([10, 1000, 10**6, LIM])
    a, b = r.randint(-k, k), r.randint(-k, k)
print(a, b)
'''
GENERATOR_CONVENTION = ("Generator reads one integer SEED from stdin and prints one test input. "
                        "Convention: seed 1 = minimum case, 2 = maximum case, 3 = edge case, others random.")
