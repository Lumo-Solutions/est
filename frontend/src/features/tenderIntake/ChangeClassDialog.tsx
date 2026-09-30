import { useState } from 'react'
import { Button } from '../../components/Button'
import { Modal } from '../../components/Modal'
import { ClassFields } from './ClassFields'
import { EMPTY_CHOICE, choiceBody, type ClassChoice } from './classChoice'
import type { ClassOption } from './treeLib'

// "Change class" for one file or a selection. The body is remounted per open (see `key` at the call
// site) so each opening starts from the file's current class.
function DialogBody({
  description,
  options,
  initial,
  onCancel,
  onApply,
}: {
  description: string
  options: ClassOption[]
  initial: ClassChoice
  onCancel: () => void
  onApply: (body: ReturnType<typeof choiceBody>) => void
}) {
  const [choice, setChoice] = useState(initial)
  return (
    <>
      <p className="mt-1 text-sm text-ink-2">{description}</p>
      <div className="mt-3">
        <ClassFields options={options} value={choice} onChange={setChoice} placeholder="Choose a class" />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" disabled={!choice.doc_class} onClick={() => onApply(choiceBody(choice))}>
          Apply class
        </Button>
      </div>
    </>
  )
}

export function ChangeClassDialog({
  open,
  title,
  description,
  options,
  initial = EMPTY_CHOICE,
  onCancel,
  onApply,
}: {
  open: boolean
  title: string
  description: string
  options: ClassOption[]
  initial?: ClassChoice
  onCancel: () => void
  onApply: (body: ReturnType<typeof choiceBody>) => void
}) {
  return (
    <Modal open={open} title={title} onClose={onCancel}>
      <DialogBody
        description={description}
        options={options}
        initial={initial}
        onCancel={onCancel}
        onApply={onApply}
      />
    </Modal>
  )
}
