import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import type { PathedFile } from '../../components/DropZone'
import { api } from '../../lib/api'
import type {
  Addendum,
  BoqPrefill,
  BulkConfirmBody,
  BulkConfirmResult,
  BulkReclassifyBody,
  CostEstimate,
  DocFilter,
  PackageControlOut,
  TreeItemPage,
  ReclassifyBody,
  TreeOut,
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
import { asCostConfirmationError } from './types'

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

const TREE_POLL_MS = 2000
/** Open item lists are refreshed at most this often while the summary's counts are changing. */
export const ITEMS_REFRESH_MS = 5000
export const ITEMS_PAGE = 100

/** True while anything is being uploaded, unpacked or read. */
export function treeIsBusy(s: { in_progress: number; pending_upload?: number; packages_processing: number }): boolean {
  return s.in_progress > 0 || (s.pending_upload ?? 0) > 0 || s.packages_processing > 0
}

/** A string that changes whenever the per-status counts move (what the open item lists key their refresh on). */
export function countsSignature(s: TreeOut['summary']): string {
  const by = Object.entries(s.by_display_status)
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([k, v]) => `${k}:${v}`)
    .join(',')
  return `${s.total}|${s.pending_upload ?? 0}|${s.needs_check}|${by}`
}

/**
 * The project page's counts (summary, groups, folders, packages: no file list). Polls the small summary every 2 s only
 * while something is uploading or being read, and, while its counts keep changing, refreshes the open item lists at
 * most every 5 s (instead of polling every page).
 */
export function useTenderTree(projectId: string | undefined) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['tender-tree', projectId],
    queryFn: ({ signal }) => api.get<TreeOut>(`/projects/${projectId}/tender-documents/tree`, signal),
    enabled: Boolean(projectId),
    refetchInterval: (q) => {
      const s = q.state.data?.summary
      return s && treeIsBusy(s) ? TREE_POLL_MS : false
    },
  })

  const summary = query.data?.summary
  const signature = summary ? countsSignature(summary) : null
  const seen = useRef<string | null>(null)
  const lastRefresh = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (signature === null) return
    const previous = seen.current
    seen.current = signature
    if (previous === null || previous === signature) return
    const refresh = () => {
      timer.current = null
      lastRefresh.current = Date.now()
      qc.invalidateQueries({ queryKey: ['tender-items', projectId] })
    }
    if (timer.current) return // a refresh is already scheduled and will pick up the latest counts
    const wait = lastRefresh.current + ITEMS_REFRESH_MS - Date.now()
    if (wait <= 0) refresh()
    else timer.current = setTimeout(refresh, wait)
  }, [signature, qc, projectId])
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )
  return query
}

export function docFilterQuery(filter: DocFilter): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(filter)) {
    if (v === undefined || v === null) continue
    if (Array.isArray(v)) {
      for (const x of v) sp.append(k, x)
    } else if (v === '' && k !== 'folder') {
      continue
    } else {
      sp.set(k, String(v))
    }
  }
  return sp.toString()
}

/** One page at a time of the files matching a filter (server-side filtering and paging). */
export function useTenderItems(
  projectId: string | undefined,
  filter: DocFilter | null,
  options: { enabled?: boolean; limit?: number } = {},
) {
  const limit = options.limit ?? ITEMS_PAGE
  return useInfiniteQuery({
    queryKey: ['tender-items', projectId, filter, limit],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => {
      const q = docFilterQuery(filter ?? {})
      return api.get<TreeItemPage>(
        `/projects/${projectId}/tender-documents/items?${q ? `${q}&` : ''}limit=${limit}&offset=${pageParam}`,
        signal,
      )
    },
    getNextPageParam: (last) => {
      const next = last.offset + last.items.length
      return last.items.length > 0 && next < last.total ? next : undefined
    },
    enabled: Boolean(projectId) && filter !== null && (options.enabled ?? true),
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
export function useInvalidateIntake(projectId?: string) {
  const qc = useQueryClient()
  return () => {
    for (const key of ['tender-tree', 'tender-items', 'tender-documents', 'tender-packages', 'tender-register', 'tender-addenda']) {
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

// `quiet` skips the per-call refresh: a cursor loop over thousands of files refreshes once at the end instead.
export function useBulkConfirm(projectId: string | undefined, options: { quiet?: boolean } = {}) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: (body: BulkConfirmBody) =>
      api.post<BulkConfirmResult>(`/projects/${projectId}/tender-documents/bulk-confirm`, body),
    onSuccess: options.quiet ? undefined : invalidate,
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

/** Change a document's class (and, with confirm, route it in the same step); routed documents re-route. */
export function useReclassifyDocument(projectId?: string) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & ReclassifyBody) =>
      api.post<TenderDocument>(`/tender-documents/${id}/reclassify`, body),
    onSuccess: invalidate,
  })
}

export function useBulkReclassify(projectId: string | undefined, options: { quiet?: boolean } = {}) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: (body: BulkReclassifyBody) =>
      api.post<BulkConfirmResult>(`/projects/${projectId}/tender-documents/bulk-reclassify`, body),
    onSuccess: options.quiet ? undefined : invalidate,
  })
}

function usePackageControl(projectId: string | undefined, action: 'pause' | 'resume' | 'cancel') {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: async (packageId: string) => {
      try {
        return await api.post<PackageControlOut>(`/tender-packages/${packageId}/${action}`)
      } catch (e) {
        // Resume can answer 409 cost-confirmation-required: surface it typed, with the estimate from the body.
        return action === 'resume' ? asCostConfirmationError(e) : Promise.reject(e)
      }
    },
    onSuccess: invalidate,
  })
}

export const usePauseTenderPackage = (projectId: string | undefined) => usePackageControl(projectId, 'pause')
export const useResumeTenderPackage = (projectId: string | undefined) => usePackageControl(projectId, 'resume')
export const useCancelTenderPackage = (projectId: string | undefined) => usePackageControl(projectId, 'cancel')

/** The estimated AI cost of reading a pack. Always fresh: it changes as files are added. */
export function useCostEstimate(packageId: string | undefined, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['tender-cost-estimate', packageId],
    queryFn: ({ signal }) => api.get<CostEstimate>(`/tender-packages/${packageId}/cost-estimate`, signal),
    enabled: Boolean(packageId) && (options.enabled ?? true),
    gcTime: 0,
    staleTime: 0,
    retry: false,
  })
}

/** Records that a lead estimator accepted `accepted_usd`; a cost-confirmation 409 carries the new estimate. */
export function useConfirmCost(projectId: string | undefined) {
  const invalidate = useInvalidateIntake(projectId)
  return useMutation({
    mutationFn: async ({ packageId, accepted_usd }: { packageId: string; accepted_usd: number }) => {
      try {
        return await api.post<CostEstimate>(`/tender-packages/${packageId}/confirm-cost`, { accepted_usd })
      } catch (e) {
        return asCostConfirmationError(e)
      }
    },
    onSuccess: invalidate,
  })
}
