import { Link, useNavigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../lib/axios';

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mockEnabled, setMockEnabled] = useState(false);

  useEffect(() => {
    api.get('/dev/mock-status/').then(r => setMockEnabled(r.data.mock_enabled)).catch(() => {});
  }, []);

  const toggleMock = async () => {
    const next = !mockEnabled;
    await api.post('/dev/toggle-mock/', { enabled: next });
    setMockEnabled(next);
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-gray-100">
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center space-x-4">
              <Link to="/catalog" className="text-xl font-bold text-indigo-600">
                RCC
              </Link>
              <Link to="/catalog" className="text-gray-700 hover:text-indigo-600 px-3 py-2 text-sm">
                Catalog
              </Link>
              <Link to="/products" className="text-gray-700 hover:text-indigo-600 px-3 py-2 text-sm">
                Products
              </Link>
              <Link to="/orders" className="text-gray-700 hover:text-indigo-600 px-3 py-2 text-sm">
                Orders
              </Link>
              {user?.role === 'ADMIN' && (
                <Link to="/admin" className="text-indigo-600 hover:text-indigo-800 px-3 py-2 text-sm font-semibold">
                  ⚡ Admin Panel
                </Link>
              )}
            </div>
            <div className="flex items-center space-x-4">
              <label className="flex items-center space-x-1 text-xs text-gray-500 cursor-pointer select-none">
                <span>Mock</span>
                <input
                  type="checkbox"
                  checked={mockEnabled}
                  onChange={toggleMock}
                  className="rounded"
                />
              </label>
              {user && (
                <span className="text-sm text-gray-600">
                  {user.username}
                </span>
              )}
              <button
                onClick={handleLogout}
                className="text-sm text-red-600 hover:text-red-800"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  );
}
