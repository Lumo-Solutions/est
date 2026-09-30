export interface ClassChoice {
  doc_class: string
  discipline: string
  drawing_type: string
}

export const EMPTY_CHOICE: ClassChoice = { doc_class: '', discipline: '', drawing_type: '' }

/** The reclassify body for a choice: discipline and drawing type only apply to drawings. */
export function choiceBody(c: ClassChoice) {
  const drawing = c.doc_class === 'drawing'
  return {
    doc_class: c.doc_class,
    sub_type: drawing && c.discipline ? c.discipline : null,
    drawing_type: drawing && c.drawing_type ? c.drawing_type : null,
  }
}

export type ChoiceBody = ReturnType<typeof choiceBody>
