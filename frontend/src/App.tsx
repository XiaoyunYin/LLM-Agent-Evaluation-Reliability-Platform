import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { OverviewPage } from './pages/OverviewPage'
import { AgentEvalPage } from './pages/AgentEvalPage'
import { RetrievalPage } from './pages/RetrievalPage'
import { JudgesPage } from './pages/JudgesPage'
import { RunsPage } from './pages/RunsPage'
import { ReviewQueuePage } from './pages/ReviewQueuePage'

/**
 * AppShell is a layout route: it renders the sidebar and topbar once, and
 * <Outlet /> swaps only the page body. Without this, every page would re-mount
 * the shell — losing scroll position and re-firing the /health check on each
 * navigation.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="agents" element={<AgentEvalPage />} />
        <Route path="retrieval" element={<RetrievalPage />} />
        <Route path="judges" element={<JudgesPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="review" element={<ReviewQueuePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
