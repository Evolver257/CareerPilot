# Evaluation datasets

`tool_calls_seed_v1.jsonl` is a development seed set, not human gold.  To promote a
case to `adjudicated_gold`, two independent annotators must review tool choice,
arguments, sequence, forbidden calls and completion criteria, then a third review
must resolve disagreements.  Record anonymized annotator IDs and the adjudicator in
the case.  The evaluation runner rejects non-adjudicated cases when
`--require-gold` is used.

Keep development and test topics separate.  Never tune prompts on the test split.
Every dataset revision gets a new version and file; do not overwrite historical
labels or evaluation outputs.
