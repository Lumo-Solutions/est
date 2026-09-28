import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  AttachInboundEmailRequest,
  BidLevelingRowOut,
  InboundEmailOut,
  QuotationAttachmentOut,
  QuotationExclusionFlagOut,
  QuotationFxRateSet,
  QuotationLineItemOut,
  QuotationOut,
  QuotationTotalOut,
  ResolveInboundTenantRequest,
} from '../../types/api'

interface DismissInboundEmailRequest {
  note: string
}

export function useInboundReviewQueue() {
  return useQuery({
    queryKey: ['quotation-inbound-review'],
    queryFn: ({ signal }) => api.get<InboundEmailOut[]>('/quotation-inbound-review', signal),
  })
}

function useInboundReviewAction(action: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: unknown }) =>
      api.post<InboundEmailOut>(`/quotation-inbound-review/${id}/${action}`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['quotation-inbound-review'] }),
  })
}

export function useResolveInboundTenant() {
  const mutation = useInboundReviewAction('resolve-tenant')
  return {
    ...mutation,
    mutate: (id: string, data: ResolveInboundTenantRequest) => mutation.mutate({ id, data }),
  }
}

export function useDismissInboundEmail() {
  const mutation = useInboundReviewAction('dismiss')
  return {
    ...mutation,
    mutate: (id: string, data: DismissInboundEmailRequest) => mutation.mutate({ id, data }),
  }
}

export function useAttachInboundEmail() {
  const mutation = useInboundReviewAction('attach')
  return {
    ...mutation,
    mutate: (id: string, data: AttachInboundEmailRequest) => mutation.mutate({ id, data }),
  }
}

export function useQuotationsForRfq(rfqId: string | undefined) {
  return useQuery({
    queryKey: ['rfqs', rfqId, 'quotations'],
    queryFn: ({ signal }) => api.get<QuotationOut[]>(`/rfqs/${rfqId}/quotations`, signal),
    enabled: Boolean(rfqId),
  })
}

export function useQuotationLineItems(quotationId: string | undefined) {
  return useQuery({
    queryKey: ['quotations', quotationId, 'line-items'],
    queryFn: ({ signal }) => api.get<QuotationLineItemOut[]>(`/quotations/${quotationId}/line-items`, signal),
    enabled: Boolean(quotationId),
  })
}

export function useQuotationExclusionFlags(quotationId: string | undefined) {
  return useQuery({
    queryKey: ['quotations', quotationId, 'exclusion-flags'],
    queryFn: ({ signal }) =>
      api.get<QuotationExclusionFlagOut[]>(`/quotations/${quotationId}/exclusion-flags`, signal),
    enabled: Boolean(quotationId),
  })
}

export function useAcknowledgeExclusionFlag(quotationId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (flagId: string) => api.post<QuotationExclusionFlagOut>(`/quotation-exclusion-flags/${flagId}/acknowledge`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['quotations', quotationId, 'exclusion-flags'] }),
  })
}

export function useQuotationAttachments(quotationId: string | undefined) {
  return useQuery({
    queryKey: ['quotations', quotationId, 'attachments'],
    queryFn: ({ signal }) => api.get<QuotationAttachmentOut[]>(`/quotations/${quotationId}/attachments`, signal),
    enabled: Boolean(quotationId),
  })
}

// GET /quotation-attachments/{id}/download redirects to a presigned S3 URL
// (backend/app/api/v1/routes/quotation_ingestion.py) -- a plain same-origin
// link lets the browser carry the session cookie and follow the redirect
// itself, same as any other authenticated GET; no need for downloadFile's
// fetch-as-blob dance (that's for POST export endpoints that return the
// file body directly, not a redirect).
export function attachmentDownloadHref(attachmentId: string): string {
  return `/api/v1/quotation-attachments/${attachmentId}/download`
}

function useLineItemAction(quotationId: string | undefined, action: 'accept' | 'reject') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (lineItemId: string) =>
      api.post<QuotationLineItemOut>(`/quotation-line-items/${lineItemId}/${action}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['quotations', quotationId, 'line-items'] }),
  })
}

export function useAcceptLineItem(quotationId: string | undefined) {
  return useLineItemAction(quotationId, 'accept')
}

export function useRejectLineItem(quotationId: string | undefined) {
  return useLineItemAction(quotationId, 'reject')
}

export function usePromoteQuotationVersion(rfqId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (quotationId: string) => api.post<QuotationOut>(`/quotations/${quotationId}/promote`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rfqs', rfqId, 'quotations'] }),
  })
}

export function useResolveCurrencyVat(rfqId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ quotationId, currency, vatInclusive }: { quotationId: string; currency: string; vatInclusive: boolean }) =>
      api.post<QuotationOut>(`/quotations/${quotationId}/resolve-currency-vat`, {
        currency,
        vat_inclusive: vatInclusive,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rfqs', rfqId, 'quotations'] }),
  })
}

export function useRejectQuotation(rfqId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ quotationId, reason }: { quotationId: string; reason: string }) =>
      api.post<QuotationOut>(`/quotations/${quotationId}/reject`, { reason }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rfqs', rfqId, 'quotations'] }),
  })
}

export function useSetQuotationFxRate() {
  return useMutation({
    mutationFn: ({ quotationId, data }: { quotationId: string; data: QuotationFxRateSet }) =>
      api.patch<QuotationOut>(`/quotations/${quotationId}/fx-rate`, data),
  })
}

export function useBidLevelingMatrix(packageId: string | undefined) {
  return useQuery({
    queryKey: ['procurement-packages', packageId, 'bid-leveling'],
    queryFn: ({ signal }) => api.get<BidLevelingRowOut[]>(`/procurement-packages/${packageId}/bid-leveling`, signal),
    enabled: Boolean(packageId),
  })
}

export function useQuotationTotals(packageId: string | undefined) {
  return useQuery({
    queryKey: ['procurement-packages', packageId, 'quotation-totals'],
    queryFn: ({ signal }) => api.get<QuotationTotalOut[]>(`/procurement-packages/${packageId}/quotation-totals`, signal),
    enabled: Boolean(packageId),
  })
}
