'use client';

export default function Home() {
  const backendUrl = 'http://localhost:8000';
  const apiUrl = `${backendUrl}/api/v1`;

  return (
    <div className="flex flex-col min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-800/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-400 to-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold">MCP</span>
            </div>
            <h1 className="text-2xl font-bold text-white">Security Proxy</h1>
          </div>
          <nav className="flex gap-6">
            <a href="#" className="text-slate-400 hover:text-white transition">Dashboard</a>
            <a href="#" className="text-slate-400 hover:text-white transition">Docs</a>
            <a href="#" className="text-slate-400 hover:text-white transition">Login</a>
          </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 w-full">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
          {/* Status Card */}
          <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-6">
            <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Backend Status</h3>
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
              <span className="text-lg font-semibold text-white">Running</span>
            </div>
            <p className="text-xs text-slate-500 mt-2">{apiUrl}</p>
          </div>

          {/* Features Card */}
          <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-6">
            <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Features</h3>
            <ul className="space-y-2 text-sm text-slate-300">
              <li>✓ JWT Authentication</li>
              <li>✓ OAuth Scopes</li>
              <li>✓ Row-Level Security</li>
            </ul>
          </div>

          {/* API Documentation Card */}
          <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-6">
            <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Quick Links</h3>
            <div className="flex flex-col gap-2">
              <a href={`${backendUrl}/docs`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 text-sm">
                → Swagger Docs
              </a>
              <a href={`${backendUrl}/api/v1/health`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 text-sm">
                → Health Check
              </a>
            </div>
          </div>
        </div>

        {/* Main Section */}
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-8">
          <h2 className="text-2xl font-bold text-white mb-4">MCP Security Proxy</h2>
          <p className="text-slate-300 mb-6">
            Welcome to the MCP Security Proxy dashboard. This system provides secure authentication, authorization, and data access control for Model Context Protocol agents.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Authentication Section */}
            <div className="border border-slate-700 rounded-lg p-6 bg-slate-900/50">
              <h3 className="text-lg font-semibold text-white mb-4">🔐 Authentication</h3>
              <p className="text-slate-400 text-sm mb-4">
                Secure your requests with JWT tokens. Learn how to authenticate with the API.
              </p>
              <a href={`${backendUrl}/docs`} className="inline-block bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm transition">
                View API Docs
              </a>
            </div>

            {/* Integration Section */}
            <div className="border border-slate-700 rounded-lg p-6 bg-slate-900/50">
              <h3 className="text-lg font-semibold text-white mb-4">🔗 Integration</h3>
              <p className="text-slate-400 text-sm mb-4">
                Integrate with Salesforce and other data sources securely.
              </p>
              <button className="inline-block bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded text-sm transition">
                Coming Soon
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-700 bg-slate-800/50 mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 text-center text-slate-500 text-sm">
          <p>MCP Security Proxy • Phase 1 Foundation</p>
        </div>
      </footer>
    </div>
  );
}
