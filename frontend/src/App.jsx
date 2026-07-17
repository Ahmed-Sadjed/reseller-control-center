import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import CatalogPage from './pages/CatalogPage';
import ProductsPage from './pages/ProductsPage';
import ReceiptPage from './pages/ReceiptPage';
import ProcessingPage from './pages/ProcessingPage';
import OrdersHistory from './pages/OrdersHistory';
import LineManagerPage from './pages/LineManagerPage';

// Admin pages
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminResellers from './pages/admin/AdminResellers';
import AdminResellerDetail from './pages/admin/AdminResellerDetail';
import AdminManualProducts from './pages/admin/AdminManualProducts';
import AdminProductDetail from './pages/admin/AdminProductDetail';
import AdminActivationCodes from './pages/admin/AdminActivationCodes';

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function AdminRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="admin-loading">
        <div className="admin-spinner"></div>
        Loading...
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (user.role !== 'ADMIN') {
    return <Navigate to="/catalog" replace />;
  }
  return children;
}

function PublicRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }
  if (user) {
    return <Navigate to="/catalog" replace />;
  }
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicRoute>
                <LoginPage />
              </PublicRoute>
            }
          />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/catalog"
            element={
              <ProtectedRoute>
                <CatalogPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/products"
            element={
              <ProtectedRoute>
                <ProductsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/receipt/:orderId"
            element={
              <ProtectedRoute>
                <ReceiptPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/processing/:orderId"
            element={
              <ProtectedRoute>
                <ProcessingPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/orders"
            element={
              <ProtectedRoute>
                <OrdersHistory />
              </ProtectedRoute>
            }
          />
          <Route
            path="/credentials/:credentialId/line-manager"
            element={
              <ProtectedRoute>
                <LineManagerPage />
              </ProtectedRoute>
            }
          />

          {/* ── Admin Routes ── */}
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <AdminDashboard />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/resellers"
            element={
              <AdminRoute>
                <AdminResellers />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/resellers/:id"
            element={
              <AdminRoute>
                <AdminResellerDetail />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/products"
            element={
              <AdminRoute>
                <AdminManualProducts />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/products/:id"
            element={
              <AdminRoute>
                <AdminProductDetail />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/codes"
            element={
              <AdminRoute>
                <AdminActivationCodes />
              </AdminRoute>
            }
          />

          <Route path="/" element={<Navigate to="/catalog" replace />} />
          <Route path="*" element={<Navigate to="/catalog" replace />} />
        </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
