import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { PathedFile } from '../../components/DropZone'
import { api } from '../../lib/api'
import type {
  Addendum,
  BoqPrefill,
  BulkConfirmBody,
  BulkConfirmResult,
  EditMetadataBody,
  RegisterFilters,
  TenderClass,
  TenderDocument,
  TenderDocumentDetail,
  TenderDocumentFilters,
  TenderDocumentPage,
  TenderPackage,
  TenderPackageAccepted,
} from './types'

export const IN_FLIGHT_STATUSES = ['received', 'processing']
const POLL_MS = 2500

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export function useTenderPackages(projectId: string | undefined) {
  return useQuery({
    queryKey: ['tender-packages', projectId],
    queryFn: ({ signal }) => api.get<TenderPackage[]>(`/projects/${projectId}/tender-packages`, signal),
    enabled: Boolean(projectId),
  })
}

export function useTenderDocuments(projectId: string | undefined, filters: TenderDocumentFilters = {}) {
  return useQuery({
    queryKey: ['tender-documents', projectId, filters],
    queryFn: ({ signal }) =>
      api.get<TenderDocumentPage>(`/projects/${projectId}/tender-documents${qs({ ...filters })}`, signal),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => IN_FLIGHT_STATUSES.includes(d.status)) ? POLL_MS : false,
  })
}

export function useTenderDocument(id: string | undefined) {
  return useQuery({
    queryKey: ['tender-document', id],
    queryFn: ({ signal }) => api.get<TenderDocumentDetail>(`/tender-documents/${id}`, signal),
    enabled: Boolean(id),
  })
}

export function useTenderClasses() {
  return useQuery({
    queryKey: ['tender-classes'],
    queryFn: ({ signal }) => api.get<TenderClass[]>('/tender-classes', signal),
    staleTime: 5 * 60 * 1000,
  })
}

export function useUpdateTenderClass() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ code, ...data }: { code: string; label?: string; enabled?: boolean; sort_order?: number }) =>
      api.patch<TenderClass>(`/tender-classes/${code}`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tender-classes'] }),
  })
}

export function useProjectAddenda(projectId: string | undefined, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['tender-addenda', projectId],
    queryFn: ({ signal }) => api.get<Addendum[]>(`/projects/${projectId}/addenda`, signal),
    enabled: Boolean(projectId) && (options.enabled ?? true),
  })
}

export function useDocumentRegister(projectId: string | undefined, filters: RegisterFilters = {}) {
  return useQuery({
    queryKey: ['tender-register', projectId, filters],
    queryFn: ({ signal }) =>
      api.get<TenderDocumentPage>(`/projects/${projectId}/document-register${qs({ ...filters })}`, signal),
    enabled: Boolean(projectId),
  })
}

export function useBoqPrefill(documentId: string | null | undefined) {
  return useQuery({
    queryKey: ['tender-boq-prefill', documentId],
    queryFn: ({ signal }) => api.get<BoqPrefill>(`/tender-documents/${documentId}/boq-prefill`, signal),
    enabled: Boolean(documentId),
    retry: false,
  })
}

// Every mutation refreshes the review grid, detail, packages, register and
// addenda for the project (prefix keys, so all filter variants refresh).
function useInvalidateIntake(projectId?: string) {
  const qc = useQueryClient()
  return () => {
    for (const key of ['tender-documents', 'tender-packages', 'tender-register', 'tender-addenda']) {
      qc.invalidateQueries({ queryKey: projectId ? [key, projectId] : [key] })
    }
    qc.invalidateQueries({ queryKey: ['tender-document'] })
  }
}

export interface CreatePackageInput {
  files: File[]
  label?: string
  transmittal_ref?: string
  received_date?: string
}

export function useCreateTenderPackage(projectId: string | undefined) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: (input: CreatePackageInput) => {
      const fd = new FormData()
      for (const f of input.files) fd.append('files', f, (f as PathedFile).relativePath ?? f.name)
      if (input.label) fd.append('label', input.label)
      if (input.transmittal_ref) fd.append('transmittal_ref', input.transmittal_ref)
      if (input.received_date) fd.append('received_date', input.received_date)
      return api.post<TenderPackageAccepted>(`/projects/${projectId}/tender-packages`, fd)
    },
    onSuccess: invalidate,
  })
}

export function useAddTenderFiles(packageId: string | undefined, projectId?: string) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    // `packageId` in the variables overrides the hook argument: a caller that only
    // learns the package id mid-flow (the upload panel) can bind the hook once.
    mutationFn: ({ files, packageId: override }: { files: File[]; packageId?: string }) => {
      const fd = new FormData()
      for (const f of files) fd.append('files', f, (f as PathedFile).relativePath ?? f.name)
      return api.post<TenderPackageAccepted>(`/tender-packages/${override ?? packageId}/files`, fd)
    },
    onSuccess: invalidate,
  })
}

export function useConfirmDocument(projectId?: string) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: (id: string) => api.post<TenderDocument>(`/tender-documents/${id}/confirm`),
    onSuccess: invalidate,
  })
}

export function useBulkConfirm(projectId: string | undefined) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: (body: BulkConfirmBody) =>
      api.post<BulkConfirmResult>(`/projects/${projectId}/tender-documents/bulk-confirm`, body),
    onSuccess: invalidate,
  })
}

export function useReclassify(projectId?: string) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: ({ id, doc_class, sub_type, note }: { id: string; doc_class: string; sub_type?: string | null; note?: string | null }) =>
      api.post<TenderDocument>(`/tender-documents/${id}/reclassify`, { doc_class, sub_type: sub_type ?? null, note: note ?? null }),
    onSuccess: invalidate,
  })
}

export function useEditMetadata(projectId?: string) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & EditMetadataBody) =>
      api.post<TenderDocument>(`/tender-documents/${id}/edit`, body),
    onSuccess: invalidate,
  })
}

export function useExclude(projectId?: string) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post<TenderDocument>(`/tender-documents/${id}/exclude`, { reason }),
    onSuccess: invalidate,
  })
}

export function useRerun(projectId?: string) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: (id: string) => api.post<TenderDocument>(`/tender-documents/${id}/rerun`),
    onSuccess: invalidate,
  })
}

/** Fetch a tender document's bytes through the same-origin content endpoint and wrap them as a File. */
export async function fetchTenderDocumentFile(documentId: string, filename: string): Promise<File> {
  const response = await fetch(`/api/v1/tender-documents/${documentId}/content`, { credentials: 'same-origin' })
  if (!response.ok) throw new Error(`Could not load the tender document file (${response.status})`)
  const blob = await response.blob()
  return new File([blob], filename, { type: blob.type })
}
