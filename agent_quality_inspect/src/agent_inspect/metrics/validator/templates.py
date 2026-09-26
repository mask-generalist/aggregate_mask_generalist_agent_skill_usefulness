TOOL_CORRECTNESS_TEMPLATE = """
As a judge, your task is to assess whether the [Argument Value] used in the tool call is correct by comparing it with the expected [Ground Truth Value]. To make this assessment, consider the context provided in the [Agent Tool Call Step] as additional information, since [Argument Value] variable is extracted from this complete source.

When the [Argument Value] and [Ground Truth Value] semantically match completely, it is considered to be COMPLETE. However, note that minor differences such as style, grammar, capitalization, punctuation, or synonyms do not affect semantic matching. If the [Argument Value] includes additional information or details that are CONSISTENT with any other arguments in the [Agent Tool Call Step], it should also be considered a correct match and must be marked as COMPLETE. However, if the additional information contradicts directly or indirectly with any other arguments in the [Agent Tool Call Step], it must be marked as INCOMPLETE. In particular, if the [Argument Value] embeds a value for a concept (such as a time, date, quantity, or location) that is ALSO represented by a separate argument in the [Agent Tool Call Step], and the embedded value differs from that separate argument's value, this is a contradiction and must be marked as INCOMPLETE, even if the embedded detail is not present in the [Ground Truth Value]. Conversely, if the [Ground Truth Value] contains a detail that is covered by a SEPARATE argument in the [Agent Tool Call Step] whose value is CONSISTENT with it, the [Argument Value] need not repeat that detail to be correct, and the match must be marked COMPLETE and not treated as missing content.

Do NOT attempt to infer or reconcile differences between values when they are clearly different or potentially contain typographical errors. This rule does not apply to values that are effectively the same: a numeric value that matches the target to the nearest whole currency unit MUST be treated as equivalent. Sub-unit or cents-level differences (for example, 12,922,923.98 vs 12,922,924), floating-point residue, and differences in thousands separators, decimal separators, or other number formatting all represent the SAME value and MUST be graded COMPLETE. A finite decimal that is a rounded or truncated approximation of the target value — including a decimal expansion of an exact fraction (for example, 0.33333 vs 1/3, or 0.667 vs 2/3) — represents the SAME value and MUST be graded COMPLETE, provided the decimal agrees with the fraction to the precision shown. The same applies to values represented in another form that is still semantically equivalent (e.g., different number formats or naming conventions that retain the same meaning). Only genuinely different magnitudes — differences larger than such rounding/formatting effects — count as clearly different and remain INCOMPLETE.

[BEGIN DATA]
************
[Argument Value]:
{arg_value}

************
[Ground Truth Value]:
{gt_value}

************
[Agent Tool Call Step]:
{agent_tool_step}

************
[END DATA]

Begin by presenting a concise argument to confirm the validity of your conclusion. Avoid simply stating the correct answers at the outset. End with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C or I. Reply with 'GRADE: C' (without quotes) to indicate COMPLETE if the [Argument Value] is correct. Otherwise, reply with 'GRADE: I' (without quotes) to indicate INCOMPLETE.
"""

DEFAULT_MODEL_GRADED_FACT_SINGLE_TURN_REMOVE_HALLUCINATION_CHECK_TEMPLATE_ONE_SUBGOAL = """
You are provided with a sample containing a gold-standard user input [Gold User Input]. Gold Expert Answer is not provided. The actual agent response is provided in section [Agent Response Submission] and the [Agent Intermediate Trajectories] section details the steps taken by the agent.

As a judge, your task is to determine whether the subgoal specified in the [Ground Truth Subgoal] has been achieved. To make this assessment, evaluate the [Agent Intermediate Trajectories] and [Agent Response Submission] to ascertain whether the subgoal has been successfully completed.

Additionally, the thought in [Agent Intermediate Trajectories]  CANNOT be considered as a substitute for a tool call and the ground truth subgoal is considered to be INCOMPLETE. Do NOT attempt to infer or reconcile differences between values when they are clearly different or potentially contain typographical errors. This rule does not apply to values that are effectively the same: a numeric value that matches the target to the nearest whole currency unit MUST be treated as equivalent. Sub-unit or cents-level differences (for example, 12,922,923.98 vs 12,922,924), floating-point residue, and differences in thousands separators, decimal separators, or other number formatting all represent the SAME value and MUST be graded COMPLETE. The same applies to values represented in another form that is still semantically equivalent (e.g., different number formats or naming conventions that retain the same meaning). Only genuinely different magnitudes — differences larger than such rounding/formatting effects — count as clearly different and remain INCOMPLETE.

[BEGIN DATA]
************
[Gold User Input]:
{questions}

************
[Ground Truth Subgoal]:
{subgoal}

************
[Agent Intermediate Trajectories]:
{trajectories}

************
[Agent Response Submission]:
{answers}

************
[END DATA]

During assessment focus solely on the factual content and the goal completion while disregarding any differences in style, grammar, punctuation, or syntax.

Begin by presenting a concise argument to confirm the validity of your conclusion. Avoid simply stating the correct answers at the outset. Decide what type of tools is required and then end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C or I. Reply with 'GRADE: C' (without quotes) to indicate COMPLETE if the agent has successfully achieved the subgoal. Otherwise, reply with 'GRADE: I' (without quotes) to indicate INCOMPLETE if the agent did not achieved the subgoal.
"""

DEFAULT_CAPABILITY_COMPLETION_TEMPLATE = """
As a judge, your task is to assess whether the agent has invoked the capability specified in the [Ground Truth Capability] by examining the tool calls recorded in the [Agent Tool Call Steps].

A capability may be fulfilled by one tool call or by a sequence of multiple tool calls that together achieve the same intent. The agent does NOT need to use the exact capability or tool named in the [Ground Truth Capability]; using a functionally equivalent capability, tool, or combination of tools that achieve the same result is equally valid. For example, using `create_file` is equivalent to using `bash` with a `cat > file` redirect, and `query_database` is equivalent to using `bash` with a raw SQL client command — what matters is that the intended effect is achieved, not the specific tool name.

IMPORTANT — wrapper and path equivalence: When the expected capability refers to a specific command or script (e.g. `ocr.recognize_file` or `word/write_to_file.py`), and the agent invokes that same command or script through a shell wrapper (e.g. `run_command`, `bash`, `exec`), a subprocess call, or by specifying a different but valid path (absolute path, relative path, nested directory path) to the SAME script or function, this MUST be treated as the SAME tool or capability — not a different one. The invocation mechanism (direct call vs. shell wrapper) and the directory path used to reach the script are irrelevant to the match classification; only the identity of the underlying command/script and its parameters matter.

Classify the match into one of the following three categories:

- EXACT_MATCH: The agent invoked the same underlying command, script, or function as the expected capability, the output match the expected values, AND the invocation completed successfully. This includes cases where the capability is called through a shell wrapper (e.g. `run_command`, `bash`) or via a different directory path (absolute or relative) to the same script — the invocation mechanism and path style do not affect the match classification. IMPORTANT: The script or command name must correspond to the ground truth capability name. A custom or ad-hoc script written by the agent that achieves the same result does NOT qualify as EXACT_MATCH. A failed invocation of the exact tool also does NOT qualify — if the exact tool was called but failed, and the result was achieved by other means, this is not EXACT_MATCH.
- FUZZY_MATCH: The agent achieved the intended capability but used a genuinely different tool, script, or approach (not merely a different invocation mechanism or path), or produced the result under a different file name or path that serves the same function. The file paths, output values, and any specific paths mentioned in the capability description do NOT need to match the expected values — what matters is that the overall capability was fulfilled and the end result is functionally equivalent, regardless of the exact paths or file locations used.
- NO_MATCH: The agent did not invoke the capability at all, or the tool calls do not achieve the intended effect.

If the capability name is not specified, EXACT_MATCH is not possible — classify as either FUZZY_MATCH or NO_MATCH only.

[BEGIN DATA]
************
[Ground Truth Capability]:
Capability name: {capability_name}
Description: {capability_description}
Expected output: {expected_output}

************
[Agent Tool Call Steps]:
{tool_call_steps}

************
[END DATA]

Begin your response with a concise argument to confirm the validity of your conclusion. End with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of E, F, or N. Reply with 'GRADE: E' (without quotes) to indicate EXACT_MATCH. Reply with 'GRADE: F' (without quotes) to indicate FUZZY_MATCH. Reply with 'GRADE: N' (without quotes) to indicate NO_MATCH.
"""

DEFAULT_MODEL_GRADED_FACT_MULTI_TURN_AT_CURRENT_TURN_REMOVE_HALLUCINATION_CHECK_TEMPLATE_ONE_SUBGOAL = """
You are provided with a sample containing a gold-standard user input at the current conversational turn in the [Gold User Input] section which may include question, instruction, or response to the agent. Gold Expert Answer are not provided. The actual agent response at the current conversational turn is provided in section [Agent Response Submission] and the [Agent Intermediate Trajectories] section details the steps taken by the agent for the current conversational turn.

For additional context, user inputs, agent trajectories, and agent responses for all the past conversational turns are also provided in the sections [Past User Inputs], [Past Agent Trajectories], and [Past Agent Responses], respectively.

As a judge, your task is to determine whether the subgoal specified in the [Ground Truth Subgoal] has been achieved for the CURRENT turn. To make this assessment, evaluate the [Agent Intermediate Trajectories] and [Agent Response Submission] that contain information of the CURRENT turn to ascertain whether the subgoal has been successfully completed.

Additionally, the thought in [Agent Intermediate Trajectories]  CANNOT be considered as a substitute for a tool call and the ground truth subgoal is considered to be INCOMPLETE. Do NOT attempt to infer or reconcile differences between values when they are clearly different or potentially contain typographical errors. This rule does not apply to values that are effectively the same: a numeric value that matches the target to the nearest whole currency unit MUST be treated as equivalent. Sub-unit or cents-level differences (for example, 12,922,923.98 vs 12,922,924), floating-point residue, and differences in thousands separators, decimal separators, or other number formatting all represent the SAME value and MUST be graded COMPLETE. The same applies to values represented in another form that is still semantically equivalent (e.g., different number formats or naming conventions that retain the same meaning). Only genuinely different magnitudes — differences larger than such rounding/formatting effects — count as clearly different and remain INCOMPLETE.

[BEGIN DATA]
************
[Past User Inputs]:
{past_user_inputs}

************
[Past Agent Trajectories]:
{past_agent_trajectories}

************
[Past Agent Responses]:
{past_agent_responses}

************
[Gold User Input]:
{questions}

************
[Ground Truth Subgoal]:
{subgoal}

************
[Agent Intermediate Trajectories]:
{trajectories}

************
[Agent Response Submission]:
{answers}

************
[END DATA]

During assessment focus solely on the factual content and the goal completion while disregarding any differences in style, grammar, punctuation, or syntax.

Begin by presenting a concise argument to confirm the validity of your conclusion. Avoid simply stating the correct answers at the outset. Decide what type of tools is required and then end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C or I. Reply with 'GRADE: C' (without quotes) to indicate COMPLETE if the agent has successfully achieved the subgoal. Otherwise, reply with 'GRADE: I' (without quotes) to indicate INCOMPLETE if the agent did not achieved the subgoal.
"""

DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_REMOVE_HALLUCINATION_CHECK_TEMPLATE_ONE_SUBGOAL = """
You are provided with a sample that contains several key components centered around an interaction between an agent and a simulated user, referred to as the user proxy. The user proxy represents a human-in-the-loop, engaging with the agent by posing questions and guiding the conversation throughout the dialogue.

The [User Summary Instructions] section outlines the user’s goals, expectations, and the overall task the agent is expected to complete. The [Agent Responses Submission] section captures the agent’s actual responses to the user proxy at each turn of the interaction. The [Agent Intermediate Trajectories] section provides a detailed step-by-step reasoning and actions taken by the agent. Finally, the [Dynamic Dialogue] section presents the full conversation between the agent and the user proxy. 

As a judge, your task is to determine whether the subgoal specified in the [Ground Truth Subgoal] has been achieved. To make this assessment, evaluate the [Agent Intermediate Trajectories] and [Agent Responses Submission] to ascertain whether the subgoal has been successfully completed.

Additionally, the thought in [Agent Intermediate Trajectories]  CANNOT be considered as a substitute for a tool call and the ground truth subgoal is considered to be INCOMPLETE. Do NOT attempt to infer or reconcile differences between values when they are clearly different or potentially contain typographical errors. This rule does not apply to values that are effectively the same: a numeric value that matches the target to the nearest whole currency unit MUST be treated as equivalent. Sub-unit or cents-level differences (for example, 12,922,923.98 vs 12,922,924), floating-point residue, and differences in thousands separators, decimal separators, or other number formatting all represent the SAME value and MUST be graded COMPLETE. The same applies to values represented in another form that is still semantically equivalent (e.g., different number formats or naming conventions that retain the same meaning). Only genuinely different magnitudes — differences larger than such rounding/formatting effects — count as clearly different and remain INCOMPLETE.

[BEGIN DATA]
************
[User Summary Instructions]:
{userTask}

************
[Ground Truth Subgoal]:
{subgoal}

************
[Agent Intermediate Trajectories]:
{trajectories}

************
[Agent Responses Submission]:
{answers}

************
[Dynamic Dialogue]:
{dynamicDialogue}
[END DATA]

During assessment focus solely on the factual content and the goal completion while disregarding any differences in style, grammar, punctuation, or syntax.

Begin by presenting a concise argument to confirm the validity of your conclusion. Avoid simply stating the correct answers at the outset. Decide what type of tools is required and then end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C or I. Reply with 'GRADE: C' (without quotes) to indicate COMPLETE if the agent has successfully achieved the subgoal. Otherwise, reply with 'GRADE: I' (without quotes) to indicate INCOMPLETE if the agent did not achieved the subgoal.
"""

DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_WITHOUT_INSTRUCT_REMOVE_HALLUCINATION_CHECK_TEMPLATE_ONE_SUBGOAL = """
You are provided with a sample that contains several key components centered around an interaction between an agent and a simulated user, referred to as the user proxy. The user proxy represents a human-in-the-loop, engaging with the agent by posing questions and guiding the conversation throughout the dialogue.

The [Agent Responses Submission] section captures the agent’s actual responses to the user proxy at each turn of the interaction. The [Agent Intermediate Trajectories] section provides a detailed step-by-step reasoning and actions taken by the agent. Finally, the [Dynamic Dialogue] section presents the full conversation between the agent and the user proxy. 

As a judge, your task is to determine whether the subgoal specified in the [Ground Truth Subgoal] has been achieved. To make this assessment, evaluate the [Agent Intermediate Trajectories] and [Agent Responses Submission] to ascertain whether the subgoal has been successfully completed.

Additionally, the thought in [Agent Intermediate Trajectories]  CANNOT be considered as a substitute for a tool call and the ground truth subgoal is considered to be INCOMPLETE. Do NOT attempt to infer or reconcile differences between values when they are clearly different or potentially contain typographical errors. This rule does not apply to values that are effectively the same: a numeric value that matches the target to the nearest whole currency unit MUST be treated as equivalent. Sub-unit or cents-level differences (for example, 12,922,923.98 vs 12,922,924), floating-point residue, and differences in thousands separators, decimal separators, or other number formatting all represent the SAME value and MUST be graded COMPLETE. The same applies to values represented in another form that is still semantically equivalent (e.g., different number formats or naming conventions that retain the same meaning). Only genuinely different magnitudes — differences larger than such rounding/formatting effects — count as clearly different and remain INCOMPLETE.

[BEGIN DATA]
************
[Ground Truth Subgoal]:
{subgoal}

************
[Agent Intermediate Trajectories]:
{trajectories}

************
[Agent Responses Submission]:
{answers}

************
[Dynamic Dialogue]:
{dynamicDialogue}
[END DATA]

During assessment focus solely on the factual content and the goal completion while disregarding any differences in style, grammar, punctuation, or syntax.

Begin by presenting a concise argument to confirm the validity of your conclusion. Avoid simply stating the correct answers at the outset. Decide what type of tools is required and then end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C or I. Reply with 'GRADE: C' (without quotes) to indicate COMPLETE if the agent has successfully achieved the subgoal. Otherwise, reply with 'GRADE: I' (without quotes) to indicate INCOMPLETE if the agent did not achieved the subgoal.
"""

# =============================================================================
# ONLINE JUDGE TEMPLATE
# Used to evaluate subgoals against completed conversations
# =============================================================================

ONLINE_JUDGE_WITHOUT_INSTRUCT_TEMPLATE = """You are provided with a sample that contains several key components centered around an interaction between an agent and a simulated user, referred to as the user proxy. The user proxy represents a human-in-the-loop, engaging with the agent by posing questions and guiding the conversation throughout the dialogue.

The [Agent Responses Submission] section captures the agent's actual responses to the user proxy at each turn of the interaction. The [Agent Intermediate Trajectories] section provides a detailed step-by-step reasoning and actions taken by the agent. Finally, the [Dynamic Dialogue] section presents the full conversation between the agent and the user proxy.

As a judge, your task is to determine whether the subgoal specified in the [Ground Truth Subgoal] has been achieved. To make this assessment, evaluate the [Agent Intermediate Trajectories] and [Agent Responses Submission] to ascertain whether the subgoal has been satisfied.

## Evaluation Outcomes
- **COMPLETE (C)**: Agent demonstrated complete adherence to this subgoal, satisfying all aspects of the behavioral criterion
- **INCOMPLETE (I)**: Agent demonstrated incomplete adherence to this subgoal, failing to satisfy the behavioral criterion
- **NA (N)**: Cannot assess adherence to this subgoal - the subgoal is not applicable to this sample (e.g., the situation never arose)


## Important Notes
- You are evaluating BEHAVIOR and PROCESS, not factual correctness.
- Base your judgment ONLY on what is observable in the [Agent Responses Submission], [Dynamic Dialogue], and [Agent Intermediate Trajectories].
- If the subgoal criterion is not applicable or irrelevant to the current sample, mark as NA.
- The thought in [Agent Intermediate Trajectories] CANNOT be considered as a substitute for a tool call.

[BEGIN DATA]
************
[Ground Truth Subgoal]:
{subgoal}

************
[Agent Intermediate Trajectories]:
{trajectories}

************
[Agent Responses Submission]:
{answers}

************
[Dynamic Dialogue]:
{dialogue_history}
[END DATA]

During assessment focus solely on the behavioral content and the criterion satisfaction while disregarding any differences in style, grammar, punctuation, or syntax.

Begin by presenting a concise explanation to confirm the validity of your conclusion. Avoid simply stating the outcome at the outset. Analyze the agent against the [Ground Truth Subgoal] criterion, then end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C, I, or N. Reply with 'GRADE: C' (without quotes) to indicate COMPLETE if the agent has demonstrated complete adherence to the subgoal. Reply with 'GRADE: I' (without quotes) to indicate INCOMPLETE if the agent demonstrated incomplete adherence to the subgoal. Reply with 'GRADE: N' (without quotes) to indicate NA if the subgoal is not applicable or irrelevant to this sample.
"""

ONLINE_JUDGE_WITHOUT_INSTRUCT_APPLICABILITY_TEMPLATE = """You are provided with a sample that contains several key components centered around an interaction between an agent and a simulated user, referred to as the user proxy. The user proxy represents a human-in-the-loop, engaging with the agent by posing questions and guiding the conversation throughout the dialogue.

The [Agent Responses Submission] section captures the agent’s actual responses to the user proxy at each turn of the interaction. The [Agent Intermediate Trajectories] section provides a detailed step-by-step reasoning and actions taken by the agent. Finally, the [Dynamic Dialogue] section presents the full conversation between the agent and the user proxy.

As a judge, your task is to determine whether the subgoal specified in the [Ground Truth Subgoal] is applicable or not applicable for the current sample. To make this assessment, evaluate the [Agent Intermediate Trajectories], [Dynamic Dialogue], and [Agent Responses Submission] to ascertain whether the subgoal is applicable or  not applicable for this sample.

## Evaluation Outcomes
- **Applicable (A)**: The conversation topic or user request relates to this subgoal's behavioral category (e.g., booking subgoals are applicable when booking is discussed; file parsing subgoals are applicable when user uploads a document)
- **NA (N)**: The conversation is about an entirely different category of action (e.g., cancellation subgoals in a booking-only conversation; invoice matching subgoals in a general inquiry conversation)

## Important Notes
- You are evaluating BEHAVIOR and PROCESS, not factual correctness.
- Base your judgment ONLY on what is observable in the [Agent Responses Submission], [Dynamic Dialogue], and [Agent Intermediate Trajectories].
- The thought in [Agent Intermediate Trajectories] CANNOT be considered as a substitute for a tool call.

## Important: Applicability Interpretation
- A subgoal is APPLICABLE if the conversation topic relates to the subgoal's behavioral category, even if the specific behavior wasn't performed.
- Consider whether the user's request falls within the same functional area as the subgoal.
- Do NOT mark as NA simply because the user didn't explicitly request the behavior.
- If the agent performed a RELATED action, then subgoals about additional/complementary actions ARE applicable (e.g., if agent searched a database, subgoals about presenting search results ARE applicable).
- Only mark as NA if the subgoal's category is completely unrelated to the conversation (e.g., password reset subgoals in a product catalog browsing conversation; file upload validation in a text-only chat).

[BEGIN DATA]
************
[Ground Truth Subgoal]:
{subgoal}

************
[Agent Intermediate Trajectories]:
{trajectories}

************
[Agent Responses Submission]:
{answers}

************
[Dynamic Dialogue]:
{dialogue_history}
[END DATA]

During assessment focus solely on the behavioral content and the criterion satisfaction while disregarding any differences in style, grammar, punctuation, or syntax.

Begin by presenting a concise explanation to confirm the validity of your conclusion. Avoid simply stating the outcome at the outset. Analyze the agent against the [Ground Truth Subgoal] criterion, then end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of A or N. Reply with 'GRADE: A' (without quotes) to indicate APPLICABLE if the subgoal is applicable and relevant to this sample. Reply with 'GRADE: N' (without quotes) to indicate NA if the subgoal is not applicable or is irrelevant to this sample.
"""
