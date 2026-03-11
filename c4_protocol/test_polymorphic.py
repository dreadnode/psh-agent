# 1. Standard Class Method
class Executor:
    def custom_slot(self, opt='config/users.yaml'):
        pass

# 2. Class Attribute (Attr before Method)
class Segment:
    n = 'config/users.yaml'
    def fragile(self):
        pass

# 3. Class Attribute (Attr after Method)
class Linker:
    def clean_len(self):
        pass
    input = 'config/users.yaml'

# 4. Decorator
@internal_task('Register')
def internal_tree(dst='config/users.yaml'):
    pass

# 5. Type Hint
def type_hinted(s: 'Portal' = 'config/users.yaml'):
    pass
