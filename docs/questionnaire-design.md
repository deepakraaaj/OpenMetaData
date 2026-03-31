# Questionnaire Design

## Principles

- ask only about ambiguity that automation cannot resolve safely
- keep each question source-specific and actionable
- include a suggested answer whenever a useful heuristic guess exists
- make answers mergeable back into the semantic model without manual transformation

## Question types

- `table_business_meaning`
- `column_business_meaning`
- `status_semantics`
- `relationship_validation`
- `sensitivity_classification`
- `chatbot_exposure`

## Merge behavior

- table meaning answers update `semantic_model.json`
- column meaning answers update the matching column artifact seed
- sensitivity answers alter display and masking flags
- validated joins become preferred joins for retrieval packages

