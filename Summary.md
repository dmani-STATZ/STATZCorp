** STATZ Web **
** Contract Management Application **


### Core Apps
1. **Contracts App**
   - Primary app for managing contracts and related entities
   - Implements modular views structure for better organization
   - Key models:
     - `Contract`: Main contract management
     - `Clin`: Contract Line Item Number management
     - `Supplier`: Supplier information and management
     - `Nsn`: National Stock Number tracking
     - `Contact`: Contact management
     - `IdiqContract`: IDIQ contract handling

2. **Inventory App**
   - Manages warehouse inventory
   - Key model:
     - `InventoryItem`: Tracks items with NSN, description, part numbers, quantities, etc.
   - Features:
     - Automatic total cost calculation
     - Location tracking
     - Purchase price management

3. **Users App**
   - Handles user management and authentication
   - Key features:
     - Microsoft OAuth integration
     - Custom user settings system
     - Announcement system
     - Permission management
   - Models:
     - `UserSetting`: Configurable user preferences
     - `Announcement`: System announcements

4. **Processing App**
   - Handles contract processing workflows
   - Key features:
     - Contract splitting functionality
     - CLIN processing
     - Matching system for buyers, suppliers, and NSNs

### Key APIs and Endpoints

1. **Contract Management APIs**
   ```python
   - /api/select-options/<field_name>/  # Dynamic select options
   - /api/clin/<clin_id>/update/       # CLIN field updates
   - /api/nsn/create/                  # NSN creation
   - /api/payment-history/             # Payment tracking
   ```

2. **Processing APIs**
   ```python
   - /api/process/split/create/        # Create contract splits
   - /api/process/split/<id>/delete/   # Delete contract splits
   - /api/process/clin/update/         # Update CLIN fields
   ```

3. **User Management APIs**
   ```python
   - /api/settings/types/              # User setting types
   - /api/permissions/                 # User permissions
   - /microsoft/callback/              # OAuth callback
   ```

### Core Functionalities

1. **Contract Management**
   - Contract creation and updates
   - CLIN management
   - Payment history tracking
   - Contract splitting
   - Document generation (DD1155 forms)
   - Supplier management
   - NSN tracking

2. **User System**
   - Flexible user settings framework
   - Role-based permissions
   - Microsoft authentication
   - Announcement system
   - Activity logging

3. **Inventory Management**
   - Item tracking with NSN
   - Quantity management
   - Cost calculations
   - Location tracking

4. **Processing Workflow**
   - Contract processing
   - CLIN processing
   - Matching system
   - Split management

5. **Form Handling**
   - Crispy Forms integration
   - Dynamic form generation
   - Form validation
   - AJAX form submissions

### Technical Features

1. **Frontend**
   - TailwindCSS for styling
   - Modern UI components
   - Dynamic form handling
   - Modal dialogs
   - AJAX interactions

2. **Security**
   - Permission-based access control
   - OAuth integration
   - Secure API endpoints
   - CSRF protection

3. **Data Management**
   - Audit trails
   - Payment history
   - Document management
   - File handling

4. **Architecture**
   - Modular view structure
   - Reusable components
   - Clean separation of concerns
   - DRY principle implementation

This appears to be a comprehensive contract management system with robust user management, inventory tracking, and processing workflows. The system follows Django best practices and implements modern web development patterns.
