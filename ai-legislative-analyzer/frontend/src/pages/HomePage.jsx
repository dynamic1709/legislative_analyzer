import React from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import {
  FileText,
  BarChart3,
  Users,
  Zap,
  ArrowRight,
  Shield,
  Lightbulb,
} from 'lucide-react'
import { useUser } from '../context/UserContext'
import '../styles/pages.css'

export default function HomePage() {
  const navigate = useNavigate()
  const { userProfile } = useUser()
  const { t } = useTranslation()

  const features = [
    {
      icon: FileText,
      title: 'Comprehensive Analysis',
      description: 'Deep dive into legislative documents with AI-powered insights',
    },
    {
      icon: BarChart3,
      title: 'Personalized Insights',
      description: 'Get analysis tailored to your profession and background',
    },
    {
      icon: Users,
      title: 'Citizen Focused',
      description: 'Understand how policies affect you and your community',
    },
    {
      icon: Zap,
      title: 'Fast Processing',
      description: 'Quick analysis with optimized token consumption',
    },
    {
      icon: Shield,
      title: 'Information Dense',
      description: 'Maximum insights with minimal information density',
    },
    {
      icon: Lightbulb,
      title: 'Smart Recommendations',
      description: 'Contextual recommendations based on your profile',
    },
  ]

  const handleGetStarted = () => {
    if (userProfile.name) {
      navigate('/upload')
    } else {
      navigate('/profile')
    }
  }

  return (
    <div className="home-page">
      {/* Hero Section */}
      <motion.section
        className="hero-section"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.8 }}
      >
        <div className="hero-content">
          <motion.h1
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.2 }}
          >
            {t('appTitle')}
          </motion.h1>
          <motion.p
            className="hero-subtitle"
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.3 }}
          >
            Understand Indian laws and policies tailored to your background
          </motion.p>

          <motion.div
            className="hero-buttons"
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.4 }}
          >
            <button
              className="btn btn-primary"
              onClick={handleGetStarted}
            >
              {t('getStarted')}
              <ArrowRight size={18} />
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => navigate('/upload')}
            >
              {t('browseExamples')}
            </button>
          </motion.div>
        </div>
      </motion.section>

      {/* Features Section */}
      <motion.section
        className="features-section"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.6 }}
      >
        <h2>Why Use AI Legislative Analyzer?</h2>
        <div className="features-grid">
          {features.map((feature, index) => {
            const Icon = feature.icon
            return (
              <motion.div
                key={index}
                className="feature-card"
                whileHover={{ y: -8 }}
                initial={{ y: 20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.1 * index }}
              >
                <div className="feature-icon">
                  <Icon size={32} />
                </div>
                <h3>{feature.title}</h3>
                <p>{feature.description}</p>
              </motion.div>
            )
          })}
        </div>
      </motion.section>

      {/* How it works */}
      <motion.section
        className="how-it-works-section"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.8 }}
      >
        <h2>How It Works</h2>
        <div className="steps-container">
          {[
            { num: 1, title: 'Create Profile', desc: 'Tell us about yourself' },
            { num: 2, title: 'Upload Document', desc: 'Upload a bill or act' },
            { num: 3, title: 'Analyze', desc: 'AI analyzes the document' },
            {
              num: 4,
              title: 'Get Insights',
              desc: 'Personalized analysis for you',
            },
          ].map((step, idx) => (
            <motion.div
              key={idx}
              className="step"
              initial={{ x: -20, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ delay: 0.1 * idx }}
            >
              <div className="step-number">{step.num}</div>
              <h4>{step.title}</h4>
              <p>{step.desc}</p>
              {idx < 3 && <ArrowRight className="step-arrow" />}
            </motion.div>
          ))}
        </div>
      </motion.section>

      {userProfile.name && (
        <motion.section
          className="user-welcome-section"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <h2>Welcome back, {userProfile.name}!</h2>
          <p>Ready to analyze more documents?</p>
          <button className="btn btn-primary" onClick={() => navigate('/upload')}>
            Continue to Analysis
          </button>
        </motion.section>
      )}
    </div>
  )
}
