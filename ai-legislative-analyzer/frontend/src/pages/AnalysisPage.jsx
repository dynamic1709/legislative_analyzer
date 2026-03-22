import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  Bookmark,
  Clock3,
  Database,
  FileText,
  FileUp,
  Gauge,
  Globe,
  Layers3,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
  Users,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { useUser } from '../context/UserContext'
import { INDIAN_LANGUAGES } from '../services/translationService'
import { apiUrl } from '../services/api'

const numberFormatter = new Intl.NumberFormat('en-IN')
const timeFormatter = new Intl.DateTimeFormat('en-IN', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const languageChoices = Object.entries(INDIAN_LANGUAGES).map(([code, label]) => ({
  code,
  label,
}))

function StatCard({ icon: Icon, label, value, detail }) {
  return (
    <motion.div className="stat-card" whileHover={{ y: -4 }}>
      <div className="stat-icon">
        <Icon size={18} />
      </div>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      <span className="stat-detail">{detail}</span>
    </motion.div>
  )
}

function MetricPill({ label, value }) {
  return (
    <div className="metric-pill">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function formatIngestionTime(timestamp) {
  if (!timestamp) {
    return 'Not yet'
  }
  return timeFormatter.format(new Date(timestamp))
}

export default function AnalysisPage() {
  const navigate = useNavigate()
  const { documentId: routeDocumentId } = useParams()
  const { userProfile, selectedLanguage, setSelectedLanguage } = useUser()
  const { t, i18n } = useTranslation()

  const [documents, setDocuments] = useState([])
  const [dashboardStats, setDashboardStats] = useState(null)
  const [ingestionStatus, setIngestionStatus] = useState(null)
  const [activeDocumentId, setActiveDocumentId] = useState(routeDocumentId || null)
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [statusMessage, setStatusMessage] = useState(
    'Upload a bill or act to start the dashboard feed.'
  )
  const [loadingDocuments, setLoadingDocuments] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [asking, setAsking] = useState(false)
  const [syncingFeed, setSyncingFeed] = useState(false)
  const fileInputRef = useRef(null)

  const activeDocument =
    documents.find((document) => document.document_id === activeDocumentId) ??
    documents[0] ??
    null
  const isBusy = loadingDocuments || uploading || asking

  const activeSummary = activeDocument?.summary_card || null
  const activeMetrics = activeDocument?.metrics || null
  const answerCitations = result?.citations || []
  const answerTokenMetrics = result?.token_metrics || {}

  const totalDocuments = dashboardStats?.document_count || documents.length
  const totalTokensSaved = dashboardStats?.total_tokens_saved || 0
  const averageCompression = dashboardStats?.average_compression_percentage || 0
  const autoIngestedCount = dashboardStats?.auto_ingested_count || 0
  const feedIsLive = ingestionStatus?.is_running || syncingFeed

  const personalizationHint = useMemo(() => {
    if (!userProfile?.name) {
      return 'Complete your profile to unlock profession-based and education-aware analysis.'
    }

    const profession = userProfile.profession || 'Citizen'
    const education = userProfile.educationLevel || 'General audience'
    return `Personalization active for ${profession} profile with ${education} explanation depth.`
  }, [userProfile])

  useEffect(() => {
    loadDocuments(routeDocumentId || null)
    loadIngestionStatus()
  }, [])

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      loadDocuments(activeDocumentId)
      loadIngestionStatus()
    }, 60000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [activeDocumentId])
  useEffect(() => {
    if (routeDocumentId) {
      setActiveDocumentId(routeDocumentId)
    }
  }, [routeDocumentId])

  async function loadDocuments(preferredDocumentId = null) {
    setLoadingDocuments(true)
    try {
      const response = await fetch(apiUrl('/documents'))
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to load dashboard feed.')
      }

      const nextDocuments = data.documents || []
      setDocuments(nextDocuments)
      setDashboardStats(data.stats || null)

      if (nextDocuments.length > 0) {
        const candidateDocumentId =
          preferredDocumentId || routeDocumentId || activeDocumentId

        const selectedDocumentId = nextDocuments.some(
          (document) => document.document_id === candidateDocumentId
        )
          ? candidateDocumentId
          : nextDocuments[0].document_id

        setActiveDocumentId(selectedDocumentId)
      } else {
        setActiveDocumentId(null)
      }
    } catch (loadError) {
      setError(loadError.message || 'Failed to load dashboard feed.')
    } finally {
      setLoadingDocuments(false)
    }
  }

  async function loadIngestionStatus() {
    try {
      const response = await fetch(apiUrl('/ingestion/status'))
      const data = await response.json()

      if (response.ok) {
        setIngestionStatus(data)
      }
    } catch (_statusError) {
      // Avoid surfacing noisy background polling errors in the main UX.
    }
  }

  const runFeedSync = async () => {
    setSyncingFeed(true)
    setError(null)
    setStatusMessage('Syncing official policy feeds and refreshing the dashboard...')

    try {
      const response = await fetch(apiUrl('/ingestion/run'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to sync policy feeds.')
      }

      const ingestedCount = data.result?.ingested_count || 0
      await Promise.all([
        loadDocuments(activeDocument?.document_id),
        loadIngestionStatus(),
      ])
      setStatusMessage(
        `Feed sync complete. ${ingestedCount} new policy updates ingested this cycle.`
      )
    } catch (syncError) {
      setError(syncError.message || 'Unable to sync the policy feed right now.')
    } finally {
      setSyncingFeed(false)
    }
  }

  const handleQuery = async () => {
    if (!query.trim() || !activeDocument) {
      return
    }

    if (!userProfile?.name) {
      setError('Please complete your citizen profile before running comprehensive analysis.')
      navigate('/profile')
      return
    }

    setAsking(true)
    setError(null)

    try {
      const response = await fetch(apiUrl('/query'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_query: query,
          document_id: activeDocument.document_id,
          user_profile: userProfile,
          output_language: selectedLanguage,
        }),
      })
      const data = await response.json()

      if (response.ok) {
        setResult(data)
        setStatusMessage(
          `Answer ready for ${activeDocument.title}. Output language: ${
            languageChoices.find((item) => item.code === selectedLanguage)?.label ||
            'English'
          }.`
        )
      } else {
        setError(data.detail || 'Failed to analyze document.')
      }
    } catch (_err) {
      setError('Failed to connect to the analyzer engine.')
    } finally {
      setAsking(false)
    }
  }

  const handleFileUpload = async (file) => {
    if (!file || file.type !== 'application/pdf') {
      setError('Please upload a valid PDF document.')
      return
    }

    setUploading(true)
    setError(null)
    setStatusMessage('Uploading, chunking, and compressing the document...')

    const formData = new FormData()
    formData.append('file', file)
    formData.append('user_profile_json', JSON.stringify(userProfile || {}))

    try {
      const response = await fetch(apiUrl('/upload'), {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()

      if (response.ok) {
        const uploadedDocument = data.document
        await loadDocuments(uploadedDocument.document_id)
        navigate(`/analysis/${uploadedDocument.document_id}`)
        setResult(null)
        setStatusMessage(
          `${uploadedDocument.title} processed. ${uploadedDocument.metrics.compression_percentage}% prompt reduction is ready for questions.`
        )
      } else {
        setError(data.detail || 'Failed to upload document.')
      }
    } catch (_err) {
      setError('Connection error during upload.')
    } finally {
      setUploading(false)
    }
  }

  const onFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFileUpload(e.target.files[0])
    }
  }

  const onDrop = (e) => {
    e.preventDefault()
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0])
    }
  }

  const onDragOver = (e) => {
    e.preventDefault()
  }

  const selectDocument = (document) => {
    setActiveDocumentId(document.document_id)
    navigate(`/analysis/${document.document_id}`)
    setResult(null)
    setError(null)
    setStatusMessage(
      `${document.title} selected. Ask a question or inspect the compressed brief.`
    )
  }

  const handleQueryKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleQuery()
    }
  }

  return (
    <div className="app-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <header className="topbar">
        <div>
          <p className="eyebrow">Multi-step Analysis Dashboard</p>
          <div className="brand-lockup">
            <div className="brand-mark">LA</div>
            <div>
              <h1>{t('comprehensiveAnalysis')}</h1>
              <p className="brand-note">
                Citizen-aware legislative insights with profession-specific framing.
              </p>
            </div>
          </div>
        </div>

        <div className="topbar-actions">
          <button
            className="btn btn-secondary"
            onClick={runFeedSync}
            disabled={syncingFeed || uploading}
          >
            <Activity size={16} />
            {syncingFeed ? t('syncingFeed') : t('syncPolicyFeed')}
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => loadDocuments(activeDocument?.document_id)}
            disabled={loadingDocuments}
          >
            <RefreshCcw size={16} /> {t('refreshFeed')}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <FileUp size={16} /> {uploading ? t('compressing') : t('uploadPdf')}
          </button>
          <input
            type="file"
            ref={fileInputRef}
            onChange={onFileSelect}
            className="hidden-input"
            accept=".pdf"
          />
        </div>
      </header>

      <main className="dashboard-layout">
        <section className="hero-panel">
          <div className="hero-copy">
            <p className="eyebrow">English-in, localized-out workflow</p>
            <h2>Ask in English. Get policy interpretation in your preferred language.</h2>
            <p className="hero-text">{personalizationHint}</p>
            <div className="status-strip">
              <Sparkles size={16} />
              <span>{statusMessage}</span>
            </div>
            <div className="ingestion-strip">
              <span className={`status-dot ${feedIsLive ? 'status-live' : 'status-idle'}`} />
              <span>Feed: {ingestionStatus?.enabled ? 'Enabled' : 'Disabled'}</span>
              <span>Sources: {ingestionStatus?.source_count || 0}</span>
              <span>Auto poll: {ingestionStatus?.poll_interval_seconds || 0}s</span>
              <span>Last run: {formatIngestionTime(ingestionStatus?.last_run_at)}</span>
            </div>
          </div>

          <div className="stats-grid">
            <StatCard
              icon={Database}
              label={t('indexedDocuments')}
              value={numberFormatter.format(totalDocuments)}
              detail="Recent acts, bills, and policy PDFs"
            />
            <StatCard
              icon={Gauge}
              label={t('averageCompression')}
              value={`${averageCompression}%`}
              detail="Prompt footprint removed before generation"
            />
            <StatCard
              icon={Layers3}
              label={t('tokensSaved')}
              value={numberFormatter.format(totalTokensSaved)}
              detail={`${numberFormatter.format(autoIngestedCount)} auto-ingested updates in feed`}
            />
            <StatCard
              icon={Activity}
              label={t('activeDocument')}
              value={activeDocument ? activeDocument.title : 'Awaiting upload'}
              detail={
                activeDocument
                  ? `${activeDocument.chunk_count} indexed chunks`
                  : 'Select a document to begin'
              }
            />
          </div>
        </section>

        <section className="workspace-grid">
          <aside className="sidebar-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{t('recentFeed')}</p>
                <h3>{t('uploadedDocuments')}</h3>
              </div>
              <span className="badge-chip">{documents.length} live</span>
            </div>

            <div
              className="upload-dropzone"
              onClick={() => fileInputRef.current?.click()}
              onDrop={onDrop}
              onDragOver={onDragOver}
            >
              <FileUp size={24} />
              <strong>
                {uploading
                  ? 'Processing your document...'
                  : t('dropPdfOrClick')}
              </strong>
              <span>Upload a new act or bill to generate a compressed feed card.</span>
            </div>

            <div className="document-feed">
              {loadingDocuments && (
                <div className="feed-empty pulse-card">Loading dashboard feed...</div>
              )}

              {!loadingDocuments && documents.length === 0 && (
                <div className="feed-empty">
                  <FileText size={24} />
                  <p>No documents indexed yet.</p>
                  <span>
                    Upload the first PDF to populate the dashboard and recent feed.
                  </span>
                </div>
              )}

              {!loadingDocuments &&
                documents.map((document) => (
                  <motion.button
                    key={document.document_id}
                    type="button"
                    className={`document-card ${
                      activeDocument?.document_id === document.document_id
                        ? 'document-card-active'
                        : ''
                    }`}
                    onClick={() => selectDocument(document)}
                    whileHover={{ y: -3 }}
                  >
                    <div className="document-card-top">
                      <strong>{document.title}</strong>
                      <span>{document.metrics.compression_percentage}% saved</span>
                    </div>
                    <p>{document.summary_card.summary}</p>
                    <div className="document-card-meta">
                      <span>
                        <Clock3 size={14} />{' '}
                        {timeFormatter.format(new Date(document.uploaded_at))}
                      </span>
                      <span>
                        <Layers3 size={14} />{' '}
                        {numberFormatter.format(document.metrics.compressed_tokens)} tokens
                      </span>
                    </div>
                  </motion.button>
                ))}
            </div>
          </aside>

          <section className="main-panel">
            {error && (
              <div className="error-banner">
                <ShieldCheck size={16} />
                <span>{error}</span>
              </div>
            )}

            {!activeDocument && !loadingDocuments && (
              <div className="empty-stage">
                <Bookmark size={28} />
                <h3>No active document yet</h3>
                <p>The dashboard becomes interactive after the first upload.</p>
              </div>
            )}

            {activeDocument && (
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeDocument.document_id}
                  className="document-stage"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -12 }}
                  transition={{ duration: 0.3 }}
                >
                  <div className="document-hero">
                    <div>
                      <p className="eyebrow">Active brief</p>
                      <h3>{activeDocument.title}</h3>
                      <p className="document-summary">{activeSummary?.summary}</p>
                    </div>

                    <div className="document-hero-meta">
                      <span className="badge-chip">{activeSummary?.compression_badge}</span>
                      <span className="soft-chip">
                        Uploaded {timeFormatter.format(new Date(activeDocument.uploaded_at))}
                      </span>
                    </div>
                  </div>

                  <div className="summary-grid">
                    <div className="summary-card wide-card">
                      <div className="panel-heading compact">
                        <div>
                          <p className="eyebrow">{t('compressedBrief')}</p>
                          <h4>{t('keyPoints')}</h4>
                        </div>
                        <Sparkles size={18} />
                      </div>
                      <div className="list-stack">
                        {(activeSummary?.key_points || []).map((point) => (
                          <div key={point} className="list-row">
                            {point}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="summary-card">
                      <div className="panel-heading compact">
                        <div>
                          <p className="eyebrow">Token metrics</p>
                          <h4>Compression footprint</h4>
                        </div>
                        <Gauge size={18} />
                      </div>
                      <div className="metric-grid">
                        <MetricPill
                          label="Original"
                          value={numberFormatter.format(activeMetrics?.original_tokens || 0)}
                        />
                        <MetricPill
                          label="Compressed"
                          value={numberFormatter.format(
                            activeMetrics?.compressed_tokens || 0
                          )}
                        />
                        <MetricPill
                          label="Saved"
                          value={numberFormatter.format(activeMetrics?.tokens_saved || 0)}
                        />
                        <MetricPill
                          label="Chunks"
                          value={numberFormatter.format(activeMetrics?.chunk_count || 0)}
                        />
                      </div>
                    </div>

                    <div className="summary-card">
                      <div className="panel-heading compact">
                        <div>
                          <p className="eyebrow">Stakeholders</p>
                          <h4>Who is impacted</h4>
                        </div>
                        <Users size={18} />
                      </div>
                      <div className="tag-grid">
                        {(activeSummary?.affected_stakeholders || []).map((stakeholder) => (
                          <span key={stakeholder} className="tag-chip">
                            {stakeholder}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="summary-card">
                      <div className="panel-heading compact">
                        <div>
                          <p className="eyebrow">Personalization</p>
                          <h4>User profile and language</h4>
                        </div>
                        <UserRound size={18} />
                      </div>
                      <div className="list-stack compact-list">
                        <div className="list-row">
                          Profession: {userProfile.profession || 'Not set'}
                        </div>
                        <div className="list-row">
                          Education: {userProfile.educationLevel || 'Not set'}
                        </div>
                        <div className="list-row">
                          Experience: {userProfile.yearsExperience ?? 0} years
                        </div>
                      </div>
                      <div className="language-row">
                        <label htmlFor="output-language">
                          <Globe size={14} /> {t('outputLanguage')}
                        </label>
                        <select
                          id="output-language"
                          value={selectedLanguage}
                          onChange={(event) => {
                            setSelectedLanguage(event.target.value)
                            i18n.changeLanguage(event.target.value)
                          }}
                        >
                          {languageChoices.map((language) => (
                            <option key={language.code} value={language.code}>
                              {language.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>

                  <div className="analysis-grid">
                    <div className="summary-card ask-card">
                      <div className="panel-heading compact">
                        <div>
                          <p className="eyebrow">Citizen query</p>
                          <h4>{t('askAboutDocument')}</h4>
                        </div>
                        <Search size={18} />
                      </div>

                      <textarea
                        className="query-input"
                        placeholder="Ask in English only. Example: What obligations does this bill create for small businesses in my sector?"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        onKeyDown={handleQueryKeyDown}
                      />

                      <div className="query-toolbar query-toolbar-wrap">
                        <span>
                          Query is English-only. Output is translated after analysis.
                        </span>
                        <button
                          className="btn btn-secondary"
                          onClick={() => navigate('/profile')}
                        >
                          {t('updateProfile')}
                        </button>
                        <button
                          className="btn btn-primary"
                          onClick={handleQuery}
                          disabled={isBusy || !query.trim()}
                        >
                          {asking ? t('analyzing') : t('askAnalyzer')}
                        </button>
                      </div>

                      <AnimatePresence>
                        {result && (
                          <motion.div
                            className="answer-panel"
                            initial={{ opacity: 0, y: 16 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: 16 }}
                          >
                            <div className="answer-header">
                              <div>
                                <p className="eyebrow">Generated answer</p>
                                <h4>Citizen-friendly interpretation</h4>
                              </div>
                              {result.cached && (
                                <span className="badge-chip">Cache hit</span>
                              )}
                            </div>

                            <div className="answer-metrics">
                              <MetricPill
                                label="Prompt tokens"
                                value={numberFormatter.format(
                                  answerTokenMetrics.total_prompt_tokens_estimate ||
                                    0
                                )}
                              />
                              <MetricPill
                                label="Context tokens"
                                value={numberFormatter.format(
                                  answerTokenMetrics.context_tokens_estimate || 0
                                )}
                              />
                              <MetricPill
                                label="Response tokens"
                                value={numberFormatter.format(
                                  answerTokenMetrics.response_tokens_estimate || 0
                                )}
                              />
                              <MetricPill
                                label="Confidence"
                                value={`${Math.max(result.confidence || 0, 0).toFixed(
                                  2
                                )}`}
                              />
                            </div>

                            <div className="answer-copy">{result.explanation}</div>

                            {result.explanation_english &&
                              selectedLanguage !== 'en' && (
                                <div className="answer-copy answer-copy-muted">
                                  <strong>English original:</strong>{' '}
                                  {result.explanation_english}
                                </div>
                              )}

                            <div className="reference-row">
                              {(result.references || []).map((reference) => (
                                <span key={reference} className="tag-chip muted-chip">
                                  {reference}
                                </span>
                              ))}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>

                    <div className="summary-card evidence-card">
                      <div className="panel-heading compact">
                        <div>
                          <p className="eyebrow">Evidence rail</p>
                          <h4>{result ? 'Retrieved citations' : 'Dashboard context'}</h4>
                        </div>
                        <FileText size={18} />
                      </div>

                      {!result && (
                        <div className="list-stack compact-list">
                          {(activeSummary?.key_points || []).map((point) => (
                            <div key={point} className="list-row">
                              {point}
                            </div>
                          ))}
                        </div>
                      )}

                      {result && (
                        <div className="citation-stack">
                          {answerCitations.map((citation) => (
                            <div
                              key={`${citation.chapter}-${citation.chunk_index}`}
                              className="citation-card"
                            >
                              <div className="citation-head">
                                <strong>{citation.chapter}</strong>
                                <span>Chunk {citation.chunk_index + 1}</span>
                              </div>
                              <p>{citation.preview}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </motion.div>
              </AnimatePresence>
            )}
          </section>
        </section>
      </main>
    </div>
  )
}
