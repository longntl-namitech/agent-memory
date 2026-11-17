"""LongMemEval answer judge: one yes/no LLM call.

Prompts follow the LongMemEval judging recipe (`evaluate_qa.py`, per question type), reproduced from memory of
the original repo and not checked against it, so the wording may differ. The official judge is GPT-4o; ours
runs on the shared client's model (gpt-5.4-nano), so scores are NOT comparable with the official leaderboard.
"""

from agent_memory.core.llm import LLMClient

_HEAD = "I will give you a question, a correct answer, and a response from a model. "
_YES = "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
_TAIL = ("\n\nQuestion: {question}\n\nCorrect Answer: {gold}\n\nModel Response: {answer}\n\n"
         "Is the model response correct? Answer yes or no only.")
_DEFAULT = (_HEAD + _YES + "If the response is equivalent to the correct answer or contains all the intermediate "
            "steps to get the correct answer, you should also answer yes. If the response only contains a subset "
            "of the information required by the answer, answer no." + _TAIL)
_PROMPTS = {
    "temporal-reasoning": _HEAD + _YES + (
        "If the response is equivalent to the correct answer or contains all the intermediate steps to get the "
        "correct answer, you should also answer yes. If the response only contains a subset of the information "
        "required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of "
        "days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one "
        "errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct.") + _TAIL,
    "knowledge-update": _HEAD + _YES + (
        "If the response contains some previous information along with an updated answer, the response should be "
        "considered as correct as long as the updated answer is the required answer.") + _TAIL,
    "single-session-preference": (
        "I will give you a question, a rubric for desired personalized response, and a response from a model. "
        "Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does "
        "not need to reflect all the points in the rubric. The response is correct as long as it recalls and "
        "utilizes the user's personal information correctly.\n\nQuestion: {question}\n\nRubric: {gold}\n\n"
        "Model Response: {answer}\n\nIs the model response correct? Answer yes or no only."),
    "abstention": (
        "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes "
        "if the model correctly identifies the question as unanswerable. The model could say that the information "
        "is incomplete, or some other information is given but the asked information is not.\n\nQuestion: "
        "{question}\n\nExplanation: {gold}\n\nModel Response: {answer}\n\nDoes the model correctly identify the "
        "question as unanswerable? Answer yes or no only."),
}


def judge(llm: LLMClient, question: str, gold: str, answer: str, qtype: str) -> bool:
    """`qtype` is the row's question_type, or "abstention" for `_abs` questions. True iff the reply starts with yes."""
    prompt = _PROMPTS.get(qtype, _DEFAULT).format(question=question, gold=gold, answer=answer)
    words = llm.chat([{"role": "user", "content": prompt}], purpose="judge").text.split()
    return bool(words) and words[0].strip(".,!:;\"'*").lower() == "yes"
