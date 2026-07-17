# Experimental Crisis-Support Boundary

AllSpark provides a minimal offline safety prompt for explicit first-person
self-harm or suicide language. It is not a clinical assessment, diagnosis,
risk score, counselling service, emergency dispatcher, or substitute for a
qualified professional. The capability remains Experimental.

## Product behavior

1. The deterministic check runs before rule-based answers and every user-facing
   local LLM path, including Web chat/streaming, CLI `llm chat`, and voice chat.
2. It ignores supported negated and clearly attributed quotation/reporting
   contexts instead of escalating on a repeated keyword count. A bare
   first-person quotation is treated conservatively as a possible disclosure.
3. It asks directly about current self-harm or suicide thoughts, immediate
   danger, and access to a means of harm.
4. Reported immediate danger prioritizes not being alone, safely reducing
   access to lethal means, and contacting locally available emergency, crisis,
   health-worker, or trusted-person support.
5. The current confirmation state is isolated by a bounded conversation ID,
   expires after ten minutes, and is held only in process memory. Anonymous or
   invalid IDs cannot create shared pending state. No sensitive answer is
   silently written to the diary, timeline, governance, or network.
6. AllSpark does not notify anyone. Every result exposes `not_sent` and
   `not_recorded` rather than implying an external action occurred.

Local contacts are optional and loaded offline from the `[crisis_support]`
section documented in [the configuration guide](CONFIGURATION.md). When none
are configured, the product states that limitation and uses a location-neutral
fallback. It does not hardcode the United States 988 service as a global answer.

## Evidence and remaining gate

The action order is informed by public guidance from the
[World Health Organization](https://www.who.int/news-room/questions-and-answers/item/suicide)
and the
[US National Institute of Mental Health](https://www.nimh.nih.gov/health/publications/5-action-steps-to-help-someone-having-thoughts-of-suicide).
These sources support direct questioning, staying with a person in immediate
danger, reducing access to lethal means, and connecting to available help.

Public guidance and automated tests are not independent product review. Before
this capability can leave Experimental, SHA-260 must contain a traceable review
of the exact bilingual prompts and flows by a qualified mental-health or
crisis-intervention expert, including qualification evidence, review date,
reservations, and the reviewed commit or content fingerprint.
