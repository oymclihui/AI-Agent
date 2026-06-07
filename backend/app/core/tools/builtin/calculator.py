from langchain_core.tools import tool


@tool
def calculator(expression: str) -> str:
    """
    Evaluates a mathematical expression and returns the result.
    Input should be a valid Python math expression like '2 + 2' or '(10 * 5) / 2'.
    """
    import ast
    import operator as op

    allowed_operators = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.Pow: op.pow,
        ast.Mod: op.mod,
        ast.USub: op.neg,
    }

    def eval_expr(node):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            return allowed_operators[type(node.op)](eval_expr(node.left), eval_expr(node.right))
        elif isinstance(node, ast.UnaryOp):
            return allowed_operators[type(node.op)](eval_expr(node.operand))
        else:
            raise ValueError(f"Unsupported expression: {node}")

    try:
        tree = ast.parse(expression, mode="eval")
        result = eval_expr(tree.body)
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {e}"


CalculatorTool = calculator
