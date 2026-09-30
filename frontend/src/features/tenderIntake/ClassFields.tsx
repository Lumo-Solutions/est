import { useId } from 'react'
import { controlClasses } from '../../components/Field'
import { DRAWING_DISCIPLINES, DRAWING_TYPES, disciplineLabel, drawingTypeLabel } from './lib'
import type { ClassChoice } from './classChoice'
import type { ClassOption } from './treeLib'

// Class select, plus discipline and drawing-type selects while the class is Drawing.
export function ClassFields({
  options,
  value,
  onChange,
  placeholder,
  compact = false,
}: {
  options: ClassOption[]
  value: ClassChoice
  onChange: (next: ClassChoice) => void
  /** When set, the class select starts on this unselectable prompt. */
  placeholder?: string
  compact?: boolean
}) {
  const id = useId()
  const label = compact ? 'mb-0.5 block text-xs text-ink-2' : 'mb-1 block text-sm text-ink'
  const control = compact ? `${controlClasses} !py-1.5 !text-sm` : controlClasses
  return (
    <div className={compact ? 'flex flex-wrap items-end gap-2' : 'space-y-3'}>
      <div>
        <label htmlFor={`${id}-class`} className={label}>
          Class
        </label>
        <select
          id={`${id}-class`}
          value={value.doc_class}
          onChange={(e) => onChange({ ...value, doc_class: e.target.value })}
          className={control}
        >
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      {value.doc_class === 'drawing' && (
        <>
          <div>
            <label htmlFor={`${id}-disc`} className={label}>
              Discipline
            </label>
            <select
              id={`${id}-disc`}
              value={value.discipline}
              onChange={(e) => onChange({ ...value, discipline: e.target.value })}
              className={control}
            >
              <option value="">Not set</option>
              {DRAWING_DISCIPLINES.map((d) => (
                <option key={d} value={d}>
                  {disciplineLabel(d)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-type`} className={label}>
              Drawing type
            </label>
            <select
              id={`${id}-type`}
              value={value.drawing_type}
              onChange={(e) => onChange({ ...value, drawing_type: e.target.value })}
              className={control}
            >
              <option value="">Not set</option>
              {DRAWING_TYPES.map((t) => (
                <option key={t} value={t}>
                  {drawingTypeLabel(t)}
                </option>
              ))}
            </select>
          </div>
        </>
      )}
    </div>
  )
}
