import React, { createContext, useContext, useState } from 'react'

const UserContext = createContext()

export function UserProvider({ children }) {
  const [userProfile, setUserProfile] = useState({
    name: '',
    profession: '',
    educationLevel: '',
    yearsExperience: 0,
    region: '',
    industry: '',
    interests: [],
  })

  const [selectedLanguage, setSelectedLanguage] = useState('en')

  const updateUserProfile = (newProfile) => {
    setUserProfile((prev) => ({ ...prev, ...newProfile }))
  }

  const clearUserProfile = () => {
    setUserProfile({
      name: '',
      profession: '',
      educationLevel: '',
      yearsExperience: 0,
      region: '',
      industry: '',
      interests: [],
    })
  }

  return (
    <UserContext.Provider
      value={{
        userProfile,
        updateUserProfile,
        clearUserProfile,
        selectedLanguage,
        setSelectedLanguage,
      }}
    >
      {children}
    </UserContext.Provider>
  )
}

export function useUser() {
  const context = useContext(UserContext)
  if (!context) {
    throw new Error('useUser must be used within UserProvider')
  }
  return context
}
