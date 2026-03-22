import React, { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import {
  FileUp,
  Loader,
  CheckCircle,
  AlertCircle,
  Trash2,
} from 'lucide-react'
import { useUser } from '../context/UserContext'
import { INDIAN_LANGUAGES } from '../services/translationService'
import { apiUrl } from '../services/api'
import '../styles/pages.css'

const languageChoices = Object.entries(INDIAN_LANGUAGES).map(([code, label]) => ({
  code,
  label,
}))

export default function DocumentUploadPage() {
  const navigate = useNavigate()
  const { userProfile, selectedLanguage, setSelectedLanguage } = useUser()
  const { t, i18n } = useTranslation()
  const fileInputRef = useRef(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [documentId, setDocumentId] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(0)

  const handleFileSelect = (file) => {
    if (!file) return

    // Validate file type
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please upload a PDF file')
      return
    }

    // Validate file size (max 50MB)
    if (file.size > 50 * 1024 * 1024) {
      setError('File size must be less than 50MB')
      return
    }

    setSelectedFile(file)
    setError(null)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    e.stopPropagation()
    const file = e.dataTransfer.files?.[0]
    handleFileSelect(file)
  }

  const handleUpload = async () => {
    if (!selectedFile) {
      setError('Please select a file')
      return
    }

    if (!userProfile.name) {
      setError('Please complete your profile first')
      xhr.open('POST', apiUrl('/upload'))
      return
    }

    setUploading(true)
    setError(null)
    setUploadProgress(0)

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)
      formData.append('user_profile_json', JSON.stringify(userProfile))

      const xhr = new XMLHttpRequest()

      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
          const progress = Math.round((e.loaded / e.total) * 100)
          setUploadProgress(progress)
        }
      })

      xhr.addEventListener('load', () => {
        if (xhr.status === 200) {
          const response = JSON.parse(xhr.responseText)
          const uploadedDocument = response.document

          if (!uploadedDocument?.document_id) {
            setError('Upload succeeded but no document id was returned.')
            setUploading(false)
            return
          }

          setDocumentId(uploadedDocument.document_id)
          setSelectedFile(null)
          setUploadProgress(100)
          setUploading(false)

          // Navigate to analysis page after a short delay
          setTimeout(() => {
            navigate(`/analysis/${uploadedDocument.document_id}`)
          }, 900)
        } else {
          const response = JSON.parse(xhr.responseText)
          setError(response.detail || 'Upload failed')
          setUploading(false)
        }
      })

      xhr.addEventListener('error', () => {
        setError('Upload failed. Please try again.')
        setUploading(false)
      })

      xhr.open('POST', apiUrl('/upload'))
      xhr.send(formData)
    } catch (err) {
      setError(err.message || 'An error occurred during upload')
      setUploading(false)
    }
  }

  return (
    <div className="upload-page">
      <div className="upload-container">
        <motion.div
          className="upload-header"
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h1>Upload Legislative Document</h1>
          <p>
            Upload a PDF file of any Indian bill or act for comprehensive
            analysis
          </p>
        </motion.div>

        {/* Language Selection */}
        <motion.div
          className="language-selector"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
        >
          <label>{t('preferredLanguage')}</label>
          <select
            value={selectedLanguage}
            onChange={(e) => {
              setSelectedLanguage(e.target.value)
              i18n.changeLanguage(e.target.value)
            }}
          >
            {languageChoices.map((language) => (
              <option key={language.code} value={language.code}>
                {language.label}
              </option>
            ))}
          </select>
        </motion.div>

        <motion.div
          className="upload-area"
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          initial={{ opacity: 0 }}
          animate={{
            opacity: 1,
            backgroundColor: selectedFile ? '#f0fdf4' : '#fafafa',
          }}
          transition={{ duration: 0.2, delay: 0.2 }}
        >
          {!documentId && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                onChange={(e) => handleFileSelect(e.target.files?.[0])}
                style={{ display: 'none' }}
              />

              <div className="upload-content">
                <FileUp size={48} />
                <h3>{t('dropPdfOrClick')}</h3>
                <p>or</p>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {t('browseFiles')}
                </button>
                <p className="upload-hint">
                  PDF files up to 50MB are supported
                </p>
              </div>
            </>
          )}

          {selectedFile && !uploading && !documentId && (
            <motion.div
              className="selected-file"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <div className="file-info">
                <div className="file-icon">📄</div>
                <div>
                  <p className="file-name">{selectedFile.name}</p>
                  <p className="file-size">
                    {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                </div>
              </div>
              <button
                className="remove-btn"
                onClick={() => {
                  setSelectedFile(null)
                  setError(null)
                }}
                type="button"
              >
                <Trash2 size={18} />
              </button>
            </motion.div>
          )}

          {uploading && (
            <motion.div
              className="upload-progress"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <Loader size={32} className="spinner" />
              <p>Uploading and analyzing document...</p>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="progress-text">{uploadProgress}%</p>
            </motion.div>
          )}

          {documentId && (
            <motion.div
              className="upload-success"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
            >
              <CheckCircle size={48} />
              <h3>Document uploaded successfully!</h3>
              <p>Redirecting to analysis...</p>
            </motion.div>
          )}
        </motion.div>

        {/* Error Message */}
        <AnimatePresence>
          {error && (
            <motion.div
              className="error-message"
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              <AlertCircle size={18} />
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Upload Button */}
        {selectedFile && !uploading && !documentId && (
          <motion.button
            className="btn btn-primary upload-btn"
            onClick={handleUpload}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            {t('uploadAndAnalyze')}
          </motion.button>
        )}

        {/* User Profile Info */}
        {userProfile.name && (
          <motion.div
            className="profile-info-card"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
          >
            <h3>Your Profile</h3>
            <div className="profile-details">
              <div className="detail-item">
                <span className="label">Name:</span>
                <span className="value">{userProfile.name}</span>
              </div>
              <div className="detail-item">
                <span className="label">Profession:</span>
                <span className="value">{userProfile.profession}</span>
              </div>
              <div className="detail-item">
                <span className="label">Education:</span>
                <span className="value">{userProfile.educationLevel}</span>
              </div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => navigate('/profile')}
              >
                Edit Profile
              </button>
            </div>
          </motion.div>
        )}
      </div>
    </div>
  )
}
