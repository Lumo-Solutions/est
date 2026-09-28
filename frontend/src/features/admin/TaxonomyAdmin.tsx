import { useMemo, useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { ConfirmModal } from '../../components/ConfirmModal'
import { Role } from '../../lib/roles'
import type { TradeNodeOut } from '../../types/api'
import { useCreateTaxonomyNode, useMoveTaxonomyNode, useTaxonomyNodes, useUpdateTaxonomyNode } from './api'

// Mirrors backend/app/api/v1/routes/taxonomy.py's _WRITE_ROLES -- notably
// NOT platform_admin, even though AdminPage is nav-gated to admin/md.
const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.MANAGING_DIRECTOR]

interface TreeNode extends TradeNodeOut {
  children: TreeNode[]
}

function buildTree(nodes: TradeNodeOut[]): TreeNode[] {
  const byId = new Map<string, TreeNode>()
  for (const n of nodes) byId.set(n.id, { ...n, children: [] })
  const roots: TreeNode[] = []
  for (const n of byId.values()) {
    const parent = n.parent_id ? byId.get(n.parent_id) : undefined
    if (parent) parent.children.push(n)
    else roots.push(n)
  }
  const bySortOrder = (a: TreeNode, b: TreeNode) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)
  const sortRecursive = (list: TreeNode[]) => {
    list.sort(bySortOrder)
    for (const n of list) sortRecursive(n.children)
  }
  sortRecursive(roots)
  return roots
}

// A node's own ltree path is a prefix of every descendant's path
// ("earthworks" is a prefix of "earthworks.excavation") -- used to keep a
// node (and anything under it) out of its own "move to" options client-side.
// The server also rejects a cyclic move (app/services/taxonomy.py's
// move_node comment: "trade_nodes_path_trg rewrites path + descendants,
// raises on cycles"), so this is a UX nicety on top of a real server
// guard, not the only thing preventing a cycle.
function isSelfOrDescendant(candidatePath: string, nodePath: string): boolean {
  return candidatePath === nodePath || candidatePath.startsWith(`${nodePath}.`)
}

function AddNodeForm({ onCancel, onSubmit }: { onCancel: () => void; onSubmit: (code: string, name: string) => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  return (
    <form
      className="mt-1 flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-slate-50 p-2"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(code, name)
      }}
    >
      <input
        placeholder="Code"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        required
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      />
      <input
        placeholder="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      />
      <button type="submit" className="rounded bg-slate-800 px-2 py-1 text-xs font-medium text-white">
        Add
      </button>
      <button type="button" onClick={onCancel} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600">
        Cancel
      </button>
    </form>
  )
}

function TaxonomyTreeNode({
  node,
  depth,
  canWrite,
  collapsed,
  onToggle,
  allNodes,
  addingChildOf,
  setAddingChildOf,
  renamingId,
  setRenamingId,
  onCreate,
  onRename,
  onToggleActive,
  onRequestMove,
}: {
  node: TreeNode
  depth: number
  canWrite: boolean
  collapsed: Set<string>
  onToggle: (id: string) => void
  allNodes: TradeNodeOut[]
  addingChildOf: string | null
  setAddingChildOf: (v: string | null) => void
  renamingId: string | null
  setRenamingId: (id: string | null) => void
  onCreate: (parentId: string, code: string, name: string) => void
  onRename: (nodeId: string, name: string) => void
  onToggleActive: (nodeId: string, isActive: boolean) => void
  onRequestMove: (nodeId: string, newParentId: string | null, label: string) => void
}) {
  const isCollapsed = collapsed.has(node.id)
  const hasChildren = node.children.length > 0
  const [renameValue, setRenameValue] = useState(node.name)
  const isRenaming = renamingId === node.id

  const moveTargets = allNodes.filter(
    (candidate) => !isSelfOrDescendant(candidate.path, node.path),
  )

  return (
    <li>
      <div className="flex flex-wrap items-center gap-1 py-1" style={{ paddingLeft: depth * 20 }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggle(node.id)}
            aria-label={isCollapsed ? `Expand ${node.name}` : `Collapse ${node.name}`}
            className="w-4 text-xs text-slate-500"
          >
            {isCollapsed ? '▸' : '▾'}
          </button>
        ) : (
          <span className="w-4" />
        )}

        {isRenaming ? (
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault()
              onRename(node.id, renameValue)
            }}
          >
            <input
              autoFocus
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              className="rounded border border-slate-300 px-1 py-0.5 text-sm"
            />
            <button type="submit" className="text-xs text-slate-600 underline">
              Save
            </button>
            <button type="button" onClick={() => setRenamingId(null)} className="text-xs text-slate-500 underline">
              Cancel
            </button>
          </form>
        ) : (
          <span
            title={node.path}
            className={`text-sm ${node.is_active ? 'text-slate-800' : 'text-slate-400 line-through'}`}
          >
            {node.name}
          </span>
        )}
        <span className="text-xs text-slate-400">({node.code})</span>

        {canWrite && !isRenaming && (
          <div className="ml-2 flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => {
                setRenameValue(node.name)
                setRenamingId(node.id)
              }}
              className="text-slate-600 underline"
            >
              Rename
            </button>
            <label className="flex items-center gap-1 text-slate-600">
              <input type="checkbox" checked={node.is_active} onChange={(e) => onToggleActive(node.id, e.target.checked)} />
              Active
            </label>
            <button type="button" onClick={() => setAddingChildOf(node.id)} className="text-slate-600 underline">
              Add child
            </button>
            <select
              value=""
              onChange={(e) => {
                const raw = e.target.value
                if (!raw) return
                const newParentId = raw === '__root__' ? null : raw
                const label = newParentId === null ? 'root (no parent)' : (allNodes.find((c) => c.id === newParentId)?.name ?? raw)
                onRequestMove(node.id, newParentId, label)
                e.target.value = ''
              }}
              className="rounded border border-slate-300 px-1 py-0.5 text-xs"
            >
              <option value="">Move to...</option>
              {node.parent_id !== null && <option value="__root__">-- root (no parent) --</option>}
              {moveTargets.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {addingChildOf === node.id && (
        <div style={{ paddingLeft: (depth + 1) * 20 }}>
          <AddNodeForm onCancel={() => setAddingChildOf(null)} onSubmit={(code, name) => onCreate(node.id, code, name)} />
        </div>
      )}

      {hasChildren && !isCollapsed && (
        <ul>
          {node.children.map((child) => (
            <TaxonomyTreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              canWrite={canWrite}
              collapsed={collapsed}
              onToggle={onToggle}
              allNodes={allNodes}
              addingChildOf={addingChildOf}
              setAddingChildOf={setAddingChildOf}
              renamingId={renamingId}
              setRenamingId={setRenamingId}
              onCreate={onCreate}
              onRename={onRename}
              onToggleActive={onToggleActive}
              onRequestMove={onRequestMove}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

export function TaxonomyAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: nodes, isLoading, isError, error } = useTaxonomyNodes(false)
  const createNode = useCreateTaxonomyNode()
  const updateNode = useUpdateTaxonomyNode()
  const moveNode = useMoveTaxonomyNode()

  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [addingChildOf, setAddingChildOf] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [pendingMove, setPendingMove] = useState<{ nodeId: string; newParentId: string | null; label: string } | null>(null)

  const allNodes = useMemo(() => nodes ?? [], [nodes])
  const tree = useMemo(() => buildTree(allNodes), [allNodes])

  const toggle = (id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const [rootCode, setRootCode] = useState('')
  const [rootName, setRootName] = useState('')

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">Trade taxonomy</h2>
      {!canWrite && <p className="mt-1 text-xs text-slate-500">Your role can view the taxonomy but not edit it.</p>}
      {canWrite && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            createNode.mutate(
              { code: rootCode, name: rootName, parent_id: null },
              { onSuccess: () => { setRootCode(''); setRootName('') } },
            )
          }}
        >
          <input placeholder="Code" value={rootCode} onChange={(e) => setRootCode(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
          <input placeholder="Name" value={rootName} onChange={(e) => setRootName(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
          <button type="submit" className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white">
            Add root node
          </button>
        </form>
      )}
      {isLoading && <p className="mt-4 text-sm text-slate-500">Loading...</p>}
      {isError && <p className="mt-4 text-sm text-red-600">{error.message}</p>}
      {createNode.isError && <p className="mt-1 text-sm text-red-600">{createNode.error.message}</p>}
      {updateNode.isError && <p className="mt-1 text-sm text-red-600">{updateNode.error.message}</p>}
      {moveNode.isError && <p className="mt-1 text-sm text-red-600">{moveNode.error.message}</p>}

      {!isLoading && !isError && (
        <ul className="mt-3">
          {tree.length === 0 && <p className="text-sm text-slate-500">No taxonomy nodes yet.</p>}
          {tree.map((n) => (
            <TaxonomyTreeNode
              key={n.id}
              node={n}
              depth={0}
              canWrite={canWrite}
              collapsed={collapsed}
              onToggle={toggle}
              allNodes={allNodes}
              addingChildOf={addingChildOf}
              setAddingChildOf={setAddingChildOf}
              renamingId={renamingId}
              setRenamingId={setRenamingId}
              onCreate={(parentId, code, name) =>
                createNode.mutate({ code, name, parent_id: parentId }, { onSuccess: () => setAddingChildOf(null) })
              }
              onRename={(nodeId, name) =>
                updateNode.mutate({ nodeId, data: { name } }, { onSuccess: () => setRenamingId(null) })
              }
              onToggleActive={(nodeId, is_active) => updateNode.mutate({ nodeId, data: { is_active } })}
              onRequestMove={(nodeId, newParentId, label) => setPendingMove({ nodeId, newParentId, label })}
            />
          ))}
        </ul>
      )}

      <ConfirmModal
        open={pendingMove !== null}
        title="Move node"
        message={pendingMove ? `Move this node under "${pendingMove.label}"?` : undefined}
        confirmLabel="Move"
        onCancel={() => setPendingMove(null)}
        onConfirm={() => {
          if (pendingMove) moveNode.mutate({ nodeId: pendingMove.nodeId, newParentId: pendingMove.newParentId })
          setPendingMove(null)
        }}
      />
    </div>
  )
}
