import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Flame, ExternalLink, Radar, Upload } from 'lucide-react'

import { importContentAccounts, importDouyinAccountLink, listContentAccounts, listMonitoredWorks } from '../api/endpoints'
import type { MonitoredWork } from '../api/types'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import ErrorAlert from '../components/ErrorAlert'
import PageHeader from '../components/PageHeader'
import Pagination from '../components/Pagination'
import { TableSkeleton } from '../components/SkeletonLoader'

const STATUS_LABELS: Record<string, string> = {
  observing: '观察中',
  hot: '火',
  very_hot: '特别火',
  insufficient_data: '数据不足',
  pending_final_window: '等待最终窗口',
  not_seen: '未采集',
}

function statusClass(status: string): string {
  if (status === 'very_hot') return 'bg-red-100 text-red-700 border-red-200'
  if (status === 'hot') return 'bg-orange-100 text-orange-700 border-orange-200'
  if (status === 'insufficient_data') return 'bg-yellow-100 text-yellow-700 border-yellow-200'
  return 'bg-gray-100 text-gray-600 border-gray-200'
}

function formatMetric(work: MonitoredWork): string {
  const detection = work.detection
  if (!detection) return '—'
  const value = detection.current_value == null ? '—' : detection.current_value.toLocaleString()
  const multiple = detection.relative_multiple == null ? '' : ` · ${detection.relative_multiple.toFixed(2)}×`
  return `${value}${multiple}`
}

function parseAccountImport(text: string) {
  const trimmed = text.trim()
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed)
      const rows = Array.isArray(parsed) ? parsed : [parsed]
      return rows.map((row) => ({
        platform: String(row.platform || 'unknown').toLowerCase(),
        external_account_id: String(row.external_account_id || row.handle || row.url),
        handle: row.handle ? String(row.handle) : undefined,
        display_name: row.display_name ? String(row.display_name) : undefined,
        profile_url: row.profile_url || row.url ? String(row.profile_url || row.url) : undefined,
      }))
    } catch {
      // Fall back to line parsing so one malformed JSON file does not break the form.
    }
  }

  return trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(',').map((part) => part.trim())
      const rawUrl = parts.length > 1 ? parts[1] : parts[0]
      let parsed: URL | null = null
      try { parsed = new URL(rawUrl) } catch { parsed = null }
      const platform = (parts.length > 1 ? parts[0] : parsed?.hostname?.split('.')[0] || 'unknown').toLowerCase()
      const path = parsed?.pathname?.split('/').filter(Boolean) ?? []
      const externalId = path[path.length - 1] || rawUrl
      return { platform, external_account_id: externalId, handle: externalId, profile_url: parsed ? rawUrl : undefined }
    })
}

export default function ContentMonitorPage() {
  const queryClient = useQueryClient()
  const [queue, setQueue] = useState<'all' | 'normal' | 'priority'>('all')
  const [page, setPage] = useState(1)
  const [showImport, setShowImport] = useState(false)
  const [importText, setImportText] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['content-monitor', queue, page],
    queryFn: () => listMonitoredWorks({ queue, page, limit: 20 }),
  })
  const { data: accountsData } = useQuery({
    queryKey: ['content-accounts'],
    queryFn: () => listContentAccounts({ page: 1, limit: 100 }),
  })
  const importMutation = useMutation({
    mutationFn: (text: string) => /(?:^|\.)douyin\.com\//i.test(text)
      ? importDouyinAccountLink(text)
      : importContentAccounts(parseAccountImport(text)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['content-accounts'] })
      setShowImport(false)
      setImportText('')
    },
  })

  if (isLoading) return <><PageHeader title="作品观察" description="只展示已采集作品及其最终热度判定（火 ≥ 3×，特别火 ≥ 5×）" /><Card padding={false}><TableSkeleton rows={8} /></Card></>
  if (error) return <ErrorAlert error={error as Error} onRetry={refetch} />

  const works = data?.data ?? []
  const meta = data?.meta

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <PageHeader title="作品观察" description="只展示已采集作品及其最终热度判定（火 ≥ 3×，特别火 ≥ 5×）" />
        <button onClick={() => setShowImport(true)} className="mt-1 inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700"><Upload size={15} />导入对标账号</button>
      </div>
      <Card>
        <div className="flex items-center justify-between mb-2"><div className="font-medium">对标账号</div><span className="text-xs text-gray-400">已导入 {accountsData?.meta?.total ?? 0} 个</span></div>
        <div className="flex flex-wrap gap-2">{(accountsData?.data ?? []).slice(0, 12).map((account) => <span key={account.id} className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-xs text-gray-600 dark:text-gray-300">{account.display_name || account.handle || account.external_account_id} · {account.platform}</span>)}{(accountsData?.data ?? []).length === 0 && <span className="text-xs text-gray-400">还没有导入对标账号</span>}</div>
      </Card>
      <div className="flex items-center gap-2 mb-4">
        {([
          ['all', '全部作品'],
          ['normal', '普通分析队列'],
          ['priority', '优先分析队列'],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            onClick={() => { setQueue(value); setPage(1) }}
            className={`px-3 py-1.5 rounded-full text-xs font-medium border ${queue === value ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}`}
          >
            {value === 'priority' && <Flame size={13} className="inline mr-1" />}
            {label}
          </button>
        ))}
      </div>
      <Card padding={false}>
        {works.length === 0 ? (
          <EmptyState icon={Radar} title="暂无作品" description="采集到对标账号作品后，这里会显示观察结果" />
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">作品</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">账号</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">最终指标</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">热度</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">状态</th>
            </tr></thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-700/50">
              {works.map((work) => (
                <tr key={work.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/40">
                  <td className="px-4 py-3 max-w-md"><div className="font-medium truncate">{work.title || work.content || work.external_work_id}</div>{work.url && <a href={work.url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 inline-flex items-center gap-1 mt-1">打开原作 <ExternalLink size={11} /></a>}</td>
                  <td className="px-4 py-3 text-gray-600">{work.account_display_name || work.account_handle || '—'}<div className="text-xs text-gray-400">{work.platform}</div></td>
                  <td className="px-4 py-3 font-mono text-xs">{formatMetric(work)}</td>
                  <td className="px-4 py-3 text-xs">{work.detection?.metric_name || '—'}</td>
                  <td className="px-4 py-3"><span className={`inline-flex px-2 py-1 rounded-full border text-xs font-medium ${statusClass(work.status)}`}>{STATUS_LABELS[work.status] || work.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {meta && meta.pages > 1 && <div className="mt-4"><Pagination page={meta.page} pages={meta.pages} total={meta.total} limit={meta.limit} onChange={setPage} /></div>}
      {showImport && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"><div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-lg p-6"><h2 className="text-lg font-semibold mb-2">导入对标账号</h2><p className="text-xs text-gray-500 mb-3">可直接粘贴抖音作品的整段分享文案，系统会解析作品并自动识别作者。其他平台仍支持每行一个账号链接、“平台,链接”或 JSON 数组。</p><textarea value={importText} onChange={(e) => setImportText(e.target.value)} className="w-full h-36 border rounded-lg p-3 text-sm dark:bg-gray-900 dark:border-gray-600" placeholder={'9.76 03/26 复制整段抖音分享文案 https://v.douyin.com/.../\n\n或：平台,https://example.com/creator'} /><input ref={fileRef} type="file" accept=".txt,.csv,.json" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (file) file.text().then(setImportText) }} />{importMutation.error && <p className="mt-2 text-xs text-red-600">{(importMutation.error as Error).message}</p>}<div className="flex justify-between mt-4"><button onClick={() => fileRef.current?.click()} className="text-sm text-blue-600">选择文件</button><div className="flex gap-2"><button onClick={() => setShowImport(false)} className="px-3 py-2 text-sm border rounded-lg">取消</button><button disabled={!importText.trim() || importMutation.isPending} onClick={() => importMutation.mutate(importText)} className="px-3 py-2 text-sm rounded-lg bg-blue-600 text-white disabled:opacity-50">{importMutation.isPending ? '正在解析…' : '开始导入'}</button></div></div></div></div>}
    </div>
  )
}
