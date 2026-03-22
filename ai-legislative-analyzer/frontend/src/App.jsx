import React from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import { UserProvider } from './context/UserContext'
import AnalysisPage from './pages/AnalysisPage'
import DocumentUploadPage from './pages/DocumentUploadPage'
import HomePage from './pages/HomePage'
import UserProfilePage from './pages/UserProfilePage'

function App() {
    return (
        <UserProvider>
            <BrowserRouter>
                <Routes>
                    <Route path="/" element={<AppLayout />}>
                        <Route index element={<HomePage />} />
                        <Route path="profile" element={<UserProfilePage />} />
                        <Route path="upload" element={<DocumentUploadPage />} />
                        <Route path="analysis" element={<AnalysisPage />} />
                        <Route path="analysis/:documentId" element={<AnalysisPage />} />
                    </Route>
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
        </UserProvider>
    )
}

export default App
