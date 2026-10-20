# Long-term memory

*[Deutsch](de/MEMORY.md) · English*

Code: `backend/src/justai/memory/`. Stored in PostgreSQL, semantic search with pgvector
(embeddings 384 dim., local with fastembed `paraphrase-multilingual-MiniLM-L12-v2`).

## Kinds of memory

| Kind | Content | Where |
| --- | --- | --- |
| working memory | running conversation context (max. 30 messages) | only in the session |
| `episode` | summaries of past conversations/events | table `memories` |
| `fact` | facts ("The cellar key is in the blue tin") | |
| `preference` | preferences ("Julian likes short answers") | |
| `procedure` | learnt behaviour (automations refer to it) | |
| `note` | free notes from the admin UI | |

In addition transcripts (`transcript_turns`), sightings and events are separate,
time-limited stores ([SECURITY.md](SECURITY.md#retention)).

## Languages

Memories are stored in the language of the conversation they come from ("Der
Kellerschlüssel liegt in der blauen Dose" stays German). The embeddings are multilingual:
an Italian question finds a German memory, and the assistant answers in the language of
the current conversation.

## Provenance

Every memory carries its origin, and the assistant is told about it:

| Provenance | Meaning | in the prompt |
| --- | --- | --- |
| `confirmed` | said or confirmed explicitly | "confirmed" |
| `observed` | observed by cameras/sensors | "observed" |
| `extracted` | extracted from a conversation | "from conversation" |
| `inferred` | a model's guess | "GUESS" |

Plus `confidence`, `importance`, `access_count`, `last_accessed_at` and a source
(session, tool, event).

## Visibility (`scope`)

* `private`: belongs to a person (`owner_person_id`) and is only visible when this person
  is recognised as the speaker.
* `room`: only relevant in one room.
* `shared`: knowledge of the household.
* `system`: maintained by the system.

An unknown speaker only sees `shared`, `system` and `room` for their room. Extraction from
conversations with an unknown speaker stores as `shared`.

## Flow

1. **Recall**: before every answer the session searches matching memories (vector search,
   minimum similarity 0.25, supplemented by keyword search) and puts them into the prompt
   with provenance and date. If the person is known, memories about them are added.
2. **Remembering explicitly**: tool `memory.remember` ("Remember …") → `confirmed`.
3. **Extraction**: after the conversation ends a job (`memory.extract`, role `memory` in
   the AI router) extracts facts and preferences from the transcript (`extracted`).
   Conversations with less than 15 characters of user text are skipped.
4. **Duplicates**: when storing, a memory with ≥ 0.92 similarity (same owner) is merged
   instead of duplicated.
5. **Consolidation** (daily, job `memory.consolidate`, also manually in the admin UI):
   * merge nearly identical memories (the one with higher provenance or the newer one
     stays),
   * contradicting facts (same subject/predicate/owner): the newest stays active, older
     ones become `superseded` (with a reference), not deleted,
   * delete guesses (`inferred`) never recalled after 90 days.
6. **Forgetting**: tools `memory.find_to_forget` + `memory.forget`. Deleting requires a
   confirmation in the conversation. In the admin UI (*Memory*) everything can be viewed,
   searched, edited and deleted.

   Forgetting is **permanent**. The content is deleted; only a tombstone with the
   embedding (without text) remains. This way the later automatic extraction from the
   transcript of an older conversation cannot restore the information: similar facts
   (≥ 0.85) are dropped, and the summary of that conversation is left out. Only an
   explicit request ("Remember …") lifts the block again. This was found in a live test:
   without the block a forgotten fact reappeared after the original session ended.

   Note: the **transcripts** themselves are a separate store with their own retention
   period (default 365 days, *Settings → Retention*). Forgetting only deletes the memory,
   not the transcript.

## Privacy

* Memories only go to cloud models if `personal_memories_to_cloud` is allowed. Otherwise
  the role `memory` or `conversation` has to run locally.
* Deleting a person deletes their private memories too.

## Tested

Against the running Docker instance (Gemini as LLM, fastembed locally):

* "Please remember: the spare key for the cellar is in the blue tin in the hall." →
  stored as `fact`, `shared`, `confirmed`.
* In a **new** session: "Where is the spare key for the cellar?" → correct answer from
  memory.
* "Please forget where the spare key is." → follow-up question, deleted after "yes".
* Live after the fix: "Remember: the code for the garden gate is 4711" → "Forget the
  code" → both sessions ended → extraction drops the fact (`skipped_forgotten: 1`), the
  memory stays empty.

These live tests were done in German.

Automated (`backend/tests/db/test_memory_forget.py`, real PostgreSQL with pgvector,
deterministic test embeddings): forgotten content is not re-extracted, invisible and
without text; remembering explicitly lifts the block; other content is still extracted.
There is no automated test for consolidation yet.
