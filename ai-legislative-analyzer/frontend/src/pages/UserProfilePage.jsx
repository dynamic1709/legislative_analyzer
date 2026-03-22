import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, AlertCircle } from 'lucide-react'
import { useUser } from '../context/UserContext'
import '../styles/pages.css'

export default function UserProfilePage() {
  const navigate = useNavigate()
  const { userProfile, updateUserProfile } = useUser()
  const [formData, setFormData] = useState(userProfile)
  const [errors, setErrors] = useState({})
  const [submitted, setSubmitted] = useState(false)

  const professions = [
    'Student',
    'Legal Professional',
    'Government Official',
    'Business Owner',
    'Healthcare Professional',
    'Teacher/Educator',
    'Farmer',
    'Journalist',
    'NGO Worker',
    'Engineer',
    'Accountant',
    'Others',
  ]

  const educationLevels = [
    'High School',
    'Diploma',
    'Bachelor',
    'Master',
    'Doctorate',
  ]

  const regions = [
    'North India',
    'South India',
    'East India',
    'West India',
    'Central India',
    'Northeast India',
  ]

  const industries = [
    'Technology',
    'Healthcare',
    'Finance',
    'Agriculture',
    'Education',
    'Manufacturing',
    'Retail',
    'Government',
    'NGO',
    'Media',
    'Others',
  ]

  const interestOptions = [
    'Employment Laws',
    'Tax Policy',
    'Healthcare Laws',
    'Education Policy',
    'Environmental Laws',
    'Labor Rights',
    'Consumer Protection',
    'Land Laws',
    'Intellectual Property',
    'Digital Privacy',
    'Social Security',
    'Business Regulations',
  ]

  const validateForm = () => {
    const newErrors = {}

    if (!formData.name.trim()) newErrors.name = 'Name is required'
    if (!formData.profession) newErrors.profession = 'Profession is required'
    if (!formData.educationLevel)
      newErrors.educationLevel = 'Education level is required'
    if (formData.yearsExperience < 0)
      newErrors.yearsExperience = 'Years of experience must be non-negative'
    if (!formData.region) newErrors.region = 'Region is required'
    if (!formData.industry) newErrors.industry = 'Industry is required'
    if (formData.interests.length === 0)
      newErrors.interests = 'Select at least one interest'

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target

    if (type === 'checkbox') {
      setFormData((prev) => ({
        ...prev,
        interests: checked
          ? [...prev.interests, value]
          : prev.interests.filter((i) => i !== value),
      }))
    } else if (name === 'yearsExperience') {
      setFormData((prev) => ({
        ...prev,
        [name]: Math.max(0, parseInt(value) || 0),
      }))
    } else {
      setFormData((prev) => ({
        ...prev,
        [name]: value,
      }))
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (validateForm()) {
      updateUserProfile(formData)
      setSubmitted(true)
      setTimeout(() => {
        navigate('/upload')
      }, 500)
    }
  }

  const handleSkip = () => {
    updateUserProfile(formData)
    navigate('/upload')
  }

  return (
    <div className="user-profile-page">
      <div className="profile-container">
        <motion.div
          className="profile-header"
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h1>Your Profile</h1>
          <p>
            Help us personalize the analysis to your background and interests
          </p>
        </motion.div>

        <motion.form
          onSubmit={handleSubmit}
          className="profile-form"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
        >
          {/* Name */}
          <div className="form-group">
            <label htmlFor="name">Full Name *</label>
            <input
              type="text"
              id="name"
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="Enter your full name"
            />
            {errors.name && (
              <span className="error">
                <AlertCircle size={16} />
                {errors.name}
              </span>
            )}
          </div>

          {/* Profession */}
          <div className="form-group">
            <label htmlFor="profession">Profession *</label>
            <select
              id="profession"
              name="profession"
              value={formData.profession}
              onChange={handleChange}
            >
              <option value="">Select your profession</option>
              {professions.map((prof) => (
                <option key={prof} value={prof}>
                  {prof}
                </option>
              ))}
            </select>
            {errors.profession && (
              <span className="error">
                <AlertCircle size={16} />
                {errors.profession}
              </span>
            )}
          </div>

          {/* Education Level */}
          <div className="form-group">
            <label htmlFor="educationLevel">Education Level *</label>
            <select
              id="educationLevel"
              name="educationLevel"
              value={formData.educationLevel}
              onChange={handleChange}
            >
              <option value="">Select education level</option>
              {educationLevels.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
            {errors.educationLevel && (
              <span className="error">
                <AlertCircle size={16} />
                {errors.educationLevel}
              </span>
            )}
          </div>

          {/* Years of Experience */}
          <div className="form-group">
            <label htmlFor="yearsExperience">Years of Experience *</label>
            <input
              type="number"
              id="yearsExperience"
              name="yearsExperience"
              value={formData.yearsExperience}
              onChange={handleChange}
              min="0"
              max="70"
            />
            {errors.yearsExperience && (
              <span className="error">
                <AlertCircle size={16} />
                {errors.yearsExperience}
              </span>
            )}
          </div>

          {/* Region */}
          <div className="form-group">
            <label htmlFor="region">Region *</label>
            <select
              id="region"
              name="region"
              value={formData.region}
              onChange={handleChange}
            >
              <option value="">Select your region</option>
              {regions.map((reg) => (
                <option key={reg} value={reg}>
                  {reg}
                </option>
              ))}
            </select>
            {errors.region && (
              <span className="error">
                <AlertCircle size={16} />
                {errors.region}
              </span>
            )}
          </div>

          {/* Industry */}
          <div className="form-group">
            <label htmlFor="industry">Industry *</label>
            <select
              id="industry"
              name="industry"
              value={formData.industry}
              onChange={handleChange}
            >
              <option value="">Select your industry</option>
              {industries.map((ind) => (
                <option key={ind} value={ind}>
                  {ind}
                </option>
              ))}
            </select>
            {errors.industry && (
              <span className="error">
                <AlertCircle size={16} />
                {errors.industry}
              </span>
            )}
          </div>

          {/* Interests */}
          <div className="form-group interests-group">
            <label>Areas of Interest *</label>
            <p className="interest-hint">Select all that apply</p>
            <div className="interests-grid">
              {interestOptions.map((interest) => (
                <div key={interest} className="interest-checkbox">
                  <input
                    type="checkbox"
                    id={interest}
                    name="interests"
                    value={interest}
                    checked={formData.interests.includes(interest)}
                    onChange={handleChange}
                  />
                  <label htmlFor={interest}>{interest}</label>
                </div>
              ))}
            </div>
            {errors.interests && (
              <span className="error">
                <AlertCircle size={16} />
                {errors.interests}
              </span>
            )}
          </div>

          {/* Action Buttons */}
          <div className="form-actions">
            <motion.button
              type="submit"
              className="btn btn-primary"
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
            >
              Continue
              <ArrowRight size={18} />
            </motion.button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleSkip}
            >
              Skip for Now
            </button>
          </div>
        </motion.form>

        {submitted && (
          <motion.div
            className="success-message"
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
          >
            ✓ Profile saved successfully!
          </motion.div>
        )}
      </div>
    </div>
  )
}
